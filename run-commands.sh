#!/usr/bin/env bash

ESP="/dev/ttyUSB0"

mkdir -p symbols dump_output
pushd hello_world
tmux new -s monitor 'idf.py -p $ESP flash monitor'
tmux kill-session -t monitor
popd
dwarf2json linux --elf hello_world/build/hello_world.elf >>symbols/symbols.json
esp-coredump -p $ESP info_corefile hello_world/build/hello_world.elf --save-core dump_output/coredump.elf >dump_output/coredump_plaintext.txt
#pushd hello_world
#idf.py coredump-info -p $ESP --core ../dump_output/coredump.elf
#popd
# esptool.py --port $ESP read_flash 0x110000 0x10000 dump_output/coredump.bin
# esp-coredump -p $ESP info_corefile --core dump_output/coredump.bin --core-format raw hello_world/build/hello_world.elf

# Updates
# With GDB debugging enabled
# idf.py -p $ESP flash monitor
# in GDB
# dump binary memory memory_image.bin 0x3ffae000 0x40000000
#
# Then run volatility with
vol -r pretty -p plugin/ -s symbols -f dump_output/memory_image.bin plugin.CNT6519Plugin --base-address 0x3ffae000 --symbols symbols
