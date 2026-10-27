from volatility3.framework import interfaces, renderers, exceptions
from volatility3.framework.configuration import requirements
from volatility3.framework.objects import utility
import logging

vollog = logging.getLogger(__name__)

class CNT6519Plugin(interfaces.plugins.PluginInterface):
    """description"""

    _required_framework_version = (2, 0, 0)

    @classmethod
    def get_requirements(cls):
        return [
            # Memory image from ESP32
            requirements.DataLayerRequirement(
                name="raw_memory",
                description="Raw ESP32 SRAM memory image"
            ),
            # Symbol Table (JSON)
            requirements.SymbolTableRequirement(
                name="freertos_symbols",
                description="FreeRTOS symbol table"
            )
        ]

    def run(self):
        return renderers.TreeGrid([("Message", str)], self._generator())

    def _generator(self):
        yield (0, ("Hello World!",))
