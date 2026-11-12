import bisect
import logging
import re
import struct
from dataclasses import dataclass
from typing import Iterator, List, Optional, Tuple

from volatility3.framework import exceptions, interfaces, objects, renderers
from volatility3.framework.configuration import requirements
from volatility3.framework.layers import segmented
from volatility3.framework.objects import utility
from volatility3.framework.renderers import format_hints
from volatility3.framework.symbols import intermed

vollog = logging.getLogger(__name__)

# Based on FreeRTOS version
TCB_TYPE_NAMES = ("tskTCB", "tskTaskControlBlock", "TCB_t")
# Single vs multicore
CURRENT_TCB_SYMBOLS = ("pxCurrentTCBs", "pxCurrentTCB")
# Max range
CODE_RANGE = (0x40000000, 0x40C00000)
# Hardcoded PC offset
SAVED_PC_OFFSET = 4
# from FreeRTOS
STACK_FILL = b"\xa5"
# Max distance to search for symbols
MAX_SYMBOL_DISTANCE = 0x10000

@dataclass
class EspTask:
    name: str
    state: str
    priority: int
    base_priority: int
    stack_used: int
    stack_free: int
    stack_pointer: int
    tcb: int
    saved_pc: int
    location: str

class EspRamLayer(segmented.SegmentedLayer):
    def _load_segments(self) -> None:
        base_layer = self.context.layers[self._base_layer]
        size = base_layer.maximum_address + 1
        base = self.config["base_address"]
        self._segments = [(base, 0, size, size)]

class CodeSymbols:
    def __init__(self, context: interfaces.context.ContextInterface, symbol_table: str):
        self._addrs: List[int] = []
        self._names: List[str] = []
        entries: List[Tuple[int, str]] = []
        try:
            table = context.symbol_space[symbol_table]
            for name in table.symbols:
                try:
                    address = table.get_symbol(name).address
                except Exception:
                    continue
                if CODE_RANGE[0] <= address < CODE_RANGE[1]:
                    entries.append((address, name))
        except (exceptions.VolatilityException, KeyError, AttributeError, TypeError) as e:
            vollog.debug(f"Could not index code symbols: {e}")
            return
        entries.sort()
        self._addrs = [a for a, _ in entries]
        self._names = [n for _, n in entries]
        vollog.debug(f"Indexed {len(entries)} code symbols")

    def locate(self, raw_pc: int) -> Tuple[int, str]:
        if not raw_pc & 0xC0000000:
            return 0, "n/a (not a code address)"
        pc = (raw_pc & 0x3FFFFFFF) | 0x40000000
        if not CODE_RANGE[0] <= pc < CODE_RANGE[1]:
            return 0, "n/a (not a code address)"
        if not self._addrs:
            return pc, "(no code symbols loaded)"
        i = bisect.bisect_right(self._addrs, pc) - 1
        if i < 0 or pc - self._addrs[i] > MAX_SYMBOL_DISTANCE:
            return pc, "(no symbol)"
        i = bisect.bisect_left(self._addrs, self._addrs[i])
        offset = pc - self._addrs[i]
        return pc, self._names[i] if offset == 0 else f"{self._names[i]}+{offset:#x}"


class CNT6519Plugin(interfaces.plugins.PluginInterface):
    """Lists FreeRTOS tasks from an ESP32 RAM image."""

    _required_framework_version = (2, 0, 0)
    _version = (3, 0, 0)

    @classmethod
    def get_requirements(cls):
        return [
            requirements.TranslationLayerRequirement(
                name="primary", description="ESP32 RAM Image"
            ),
            requirements.StringRequirement(
                name="symbols",
                description="Name of the symbol file to use",
                optional=False
            ),
            requirements.StringRequirement(
                name="base_address",
                description="Target address of byte 0 of the RAM image, e.g. 0x3ffae000",
                optional=False
            ),
        ]

    # Walk FreeRTOS tasks
    @classmethod
    def list_tasks(
        cls,
        context: interfaces.context.ContextInterface,
        layer_name: str,
        symbol_table: str,
    ) -> Iterator[EspTask]:
        module = context.module(symbol_table, layer_name=layer_name, offset=0)
        layer = context.layers[layer_name]

        def has_symbol(name: str) -> bool:
            try:
                module.get_symbol(name)
                return True
            except exceptions.SymbolError:
                return False

        def has_type(name: str) -> bool:
            try:
                module.get_type(name)
                return True
            except exceptions.SymbolError:
                return False

        def as_list(obj) -> list:
            return list(obj) if isinstance(obj, objects.Array) else [obj]

        tcb_type = next((n for n in TCB_TYPE_NAMES if has_type(n)), None)
        if tcb_type is None:
            raise Exception(f"No TCB struct ({' / '.join(TCB_TYPE_NAMES)}) in the symbol table")

        cur_symbol = next((n for n in CURRENT_TCB_SYMBOLS if has_symbol(n)), None)
        if cur_symbol is None:
            raise Exception(f"None of {CURRENT_TCB_SYMBOLS} found in the symbol table")

        expected: Optional[int] = None
        try:
            current = {int(p) for p in as_list(module.object_from_symbol(cur_symbol)) if int(p)}
            if has_symbol("uxCurrentNumberOfTasks"):
                expected = int(module.object_from_symbol("uxCurrentNumberOfTasks"))
        except exceptions.InvalidAddressException as e:
            raise Exception(
                "Scheduler globals are outside the image"
            ) from e
        if expected is not None and not (0 < expected <= 1024):
            raise Exception(
                f"uxCurrentNumberOfTasks reads as {expected}, which is not within expected range"
            )
        vollog.debug(f"Current TCB(s): {[hex(p) for p in current]}")

        code = CodeSymbols(context, symbol_table)

        # FreeRTOS lists that can hold a task
        task_lists: List[Tuple[str, object]] = []
        for state, symbol in (
            ("Ready", "pxReadyTasksLists"),
            ("Blocked", "xDelayedTaskList1"),
            ("Blocked", "xDelayedTaskList2"),
            ("Pending Ready", "xPendingReadyList"),
            ("Suspended", "xSuspendedTaskList"),
            ("Terminating", "xTasksWaitingTermination"),
        ):
            if has_symbol(symbol):
                for lst in as_list(module.object_from_symbol(symbol)):
                    task_lists.append((state, lst))

        found = set()
        for state, lst in task_lists:
            for tcb_addr in cls._list_owners(module, lst):
                if tcb_addr in found:
                    continue
                found.add(tcb_addr)
                running = tcb_addr in current
                yield cls._read_task(module, layer, code, tcb_type, tcb_addr,
                                     "Running" if running else state, running)

        for tcb_addr in current - found:
            found.add(tcb_addr)
            yield cls._read_task(module, layer, code, tcb_type, tcb_addr, "Running", True)

        if expected is not None and expected != len(found):
            vollog.warning(
                f"uxCurrentNumberOfTasks={expected} but {len(found)} task(s) recovered"
            )

    @staticmethod
    def _list_owners(module, lst) -> Iterator[int]:
        try:
            n_items = int(lst.uxNumberOfItems)
            if not n_items:
                return
            end_marker = lst.xListEnd.vol.offset
            item_addr = int(lst.xListEnd.pxNext)
            seen = set()
            while item_addr and item_addr != end_marker and item_addr not in seen and len(seen) <= n_items:
                seen.add(item_addr)
                item = module.object(object_type="ListItem_t", offset=item_addr, absolute=True)
                owner = int(item.pvOwner)
                if owner:
                    yield owner
                item_addr = int(item.pxNext)
        except exceptions.InvalidAddressException:
            return

    @staticmethod
    def _stack_usage(layer, tcb) -> Tuple[int, int, Optional[int], Optional[int]]:
        try:
            low, high = int(tcb.pxStack), int(tcb.pxEndOfStack)
        except AttributeError:
            return -1, -1, None, None
        if high <= low:
            return -1, -1, None, None
        try:
            data = layer.read(low, high - low)
        except exceptions.InvalidAddressException:
            return -1, -1, low, high
        untouched = len(data) - len(data.lstrip(STACK_FILL))
        free = untouched - untouched % 4
        return len(data) - free, free, low, high

    @staticmethod
    def _saved_location(layer, code: CodeSymbols, top: int,
                        low: Optional[int], high: Optional[int]) -> Tuple[int, str]:
        if low is not None and not (low <= top <= high):
            return 0, "N/A: Outside stack"
        try:
            (raw_pc,) = struct.unpack("<I", layer.read(top + SAVED_PC_OFFSET, 4))
        except exceptions.InvalidAddressException:
            return 0, "N/A: Outside image"
        return code.locate(raw_pc)

    # Compile a task with relevant data
    @classmethod
    def _read_task(cls, module, layer, code: CodeSymbols, tcb_type: str,
                   tcb_addr: int, state: str, running: bool) -> EspTask:
        try:
            tcb = module.object(object_type=tcb_type, offset=tcb_addr, absolute=True)
            name = str(utility.array_to_string(tcb.pcTaskName)).split("\x00", 1)[0] or "<unnamed>"
            priority = int(tcb.uxPriority)
            top = int(tcb.pxTopOfStack)
            base_priority = int(tcb.uxBasePriority)
            used, free, low, high = cls._stack_usage(layer, tcb)
        except exceptions.InvalidAddressException:
            return EspTask("<TCB not in dump>", state, -1, -1, -1, -1, 0, tcb_addr, 0, "n/a")

        if running:
            # Running programs will never find the address :(
            pc, where = 0, "Running"
        else:
            pc, where = cls._saved_location(layer, code, top, low, high)
        return EspTask(name, state, priority, base_priority, used, free, top, tcb_addr, pc, where)

    # Build our ram image from the input RAM file
    def _build_esp_layer(self, base_address: int) -> str:
        name = self.context.layers.free_layer_name("EspRamLayer")
        self.context.config[interfaces.configuration.path_join(name, "base_layer")] = self.config["primary"]
        self.context.config[interfaces.configuration.path_join(name, "base_address")] = base_address
        self.context.add_layer(EspRamLayer(self.context, name, name))
        return name

    # Generator function used by volatility
    def _generator(self):
        def error_row(message: str):
            hx = format_hints.Hex(0)
            return (0, ("Error", message, 0, 0, 0, 0, hx, hx, hx, ""))

        # Get the base address (unique, taken as an arg)
        base_arg = self.config.get("base_address", None)
        try:
            base_address = int(str(base_arg), 0)
        except ValueError:
            vollog.error("--base-address must be the target address of byte 0, e.g. 0x3ffae000")
            yield error_row("bad --base-address")
            return

        # Get the symbols since volatility cannot locate them
        isf_name = re.sub(r"\.json(\.xz|\.gz)?$", "", str(self.config["symbols"]))
        try:
            symbol_table = intermed.IntermediateSymbolTable.create(
                self.context, self.config_path, "", isf_name
            )
        except (ValueError, OSError, exceptions.VolatilityException) as e:
            vollog.error(f"Could not load symbol file '{isf_name}'")
            yield error_row("symbol file not found")
            return

        # Prepare the RAM image
        layer_name = self._build_esp_layer(base_address)

        # Meat of the generator, get each task and print info about it according to format
        try:
            for t in self.list_tasks(self.context, layer_name, symbol_table):
                yield (
                    0,
                    (
                        t.name,
                        t.state,
                        t.priority,
                        t.base_priority,
                        t.stack_used,
                        t.stack_free,
                        format_hints.Hex(t.stack_pointer),
                        format_hints.Hex(t.tcb),
                        format_hints.Hex(t.saved_pc),
                        t.location,
                    ),
                )
        except Exception as e:
            vollog.error(str(e))
            yield error_row("symbols do not match image")

    # Volatility plugin required function
    def run(self):
        return renderers.TreeGrid(
            [
                ("Task Name", str),
                ("State", str),
                ("Priority", int),
                ("Base Priority", int),
                ("Stack Used", int),
                ("Stack Free", int),
                ("Stack Pointer", format_hints.Hex),
                ("TCB Address", format_hints.Hex),
                ("Saved PC", format_hints.Hex),
                ("Location", str),
            ],
            self._generator(),
        )
