# Configuración OpenRAM del banco de registros de femto_UN:
# 32 palabras x 32 bits, 1 puerto RW + 1 puerto R ("dual access"), sky130A.
# Con dos puertos se leen rs1 y rs2 a la vez (un solo ciclo de lectura).
#
# Compilar:  python3 sram_compiler.py sram_32x32_1rw1r_config.py   (con OPENRAM_HOME,
# OPENRAM_TECH y PYTHONPATH exportados, dentro de `nix develop`).

word_size      = 32
num_words      = 32
write_size     = 8       # escritura por byte -> wmask0[3:0]
words_per_row  = 1

num_rw_ports   = 1
num_r_ports    = 1
num_w_ports    = 0

# La celda dual-port de sky130 (8T) es distinta de la single-port: comprobar si el
# generador exige columna de reserva; si la genera, aparecerá spare_wen0 y din0/dout0
# de 33 bits en el .v y habrá que actualizar blackbox, wrapper y modelo.
num_spare_cols = 0

tech_name      = "sky130A"
nominal_corner_only = True
analytical_delay    = True
route_supplies      = "ring"
check_lvsdrc        = True

output_name = "sky130_sram_32x32_1rw1r"
output_path = "macro_32x32_1rw1r"
