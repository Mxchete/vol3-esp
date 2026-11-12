idf_component_register(SRCS "hello_world_main.c"
                       PRIV_REQUIRES spi_flash espcoredump
                       REQUIRES esp_gdbstub
                       INCLUDE_DIRS "")
