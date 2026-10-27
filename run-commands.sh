#!/usr/bin/env bash

ESP="/dev/ttyUSB0"

pushd hello_world
idf.py -p $ESP flash
popd
dwarf2json linux --elf hello_world/build/hello_world.elf >>symbols/symbols.json
esp-coredump -p $ESP info_corefile hello_world/build/hello_world.elf --save-core dump_output/coredump.elf
pushd hello_world
idf.py coredump-info -p $ESP --core ../dump_output/coredump.elf
popd
