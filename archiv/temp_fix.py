# Temporärer Fix: Entferne dead Code ab Zeile 878
# Von "detailed_objects = []" bis vor "async def kulturpool_get_institutions_handler"

# Das Problem: Es gibt dead Code zwischen Zeile 878 und ca. 1000
# Der gesamte Block nach dem ersten return Statement ist unreachable

print("Dead Code Removal Plan:")
print("1. Finde 'detailed_objects = []' - das ist der Beginn des dead Code")
print("2. Finde 'async def kulturpool_get_institutions_handler' - das ist das Ende")  
print("3. Entferne alles dazwischen")
