# Multi-Account Executor — AddOn para NinjaTrader 8

AddOn (ventana propia, no Indicator/Strategy) que automatiza una entrada dual
(Buy Stop + Sell Stop) sobre una **cuenta maestra**, gestiona el trade
(Break Even, Trailing Stop, límite de pérdida diaria, entrada programada,
disparo por pico de volumen) y **replica cada fill de la maestra hacia otras
cuentas** que elijas, con un multiplicador de tamaño configurable por cuenta.

Es funcionalmente equivalente al panel que me mostraste (entrada dual,
break even, trailing stop, límite diario, entrada programada, Auto Volume
Pro, monitoreo en vivo) más el replicador multi-cuenta que pediste, pero con
nombre y UI propios — no reproduce el branding ni el diseño visual de
ningún producto de terceros.

## ⚠️ Antes de usar esto con dinero real

- **No lo he podido compilar ni probar.** Este sandbox no tiene NinjaTrader 8
  instalado, así que el código está escrito siguiendo los patrones
  documentados de la API de NinjaScript/Cbi para AddOns, pero **vos sos quien
  lo compila por primera vez** en el NinjaScript Editor de tu instalación.
  Es esperable tener que ajustar 2-3 detalles de firma de API (ver más abajo).
- **Probalo exclusivamente en cuentas Sim (Sim101, etc.) durante varios días**,
  con tamaños pequeños, antes de pensar en conectarlo a una cuenta real.
- El replicador multi-cuenta **multiplica el riesgo**: un error de
  configuración no afecta una cuenta, afecta todas las que tengas marcadas
  como réplica. Verificá el ratio de cada una antes de tocar Launch.
- El límite de pérdida diaria se evalúa **por cuenta**, cada ~1 segundo, y
  solo actúa después de que la posición ya existe — no es una garantía
  instantánea de que nunca vas a perder más de lo configurado (slippage,
  gaps, latencia de red).

## Estructura

| Archivo | Rol |
|---|---|
| `AccountSlot.cs` | Estado de una cuenta (maestra o réplica): órdenes vivas, posición, PnL de la sesión. |
| `ExecutionParameters.cs` | Snapshot de todos los parámetros del panel. |
| `MultiAccountExecutorEngine.cs` | Toda la lógica de órdenes/replicación/riesgo. Sin UI. |
| `MultiAccountExecutorWindow.cs` | Panel WPF (`NTWindow`): inputs, monitoreo en vivo, log. |
| `MultiAccountExecutorAddOn.cs` | Registra el ítem de menú "Multi-Account Executor" en Control Center → New. |

## Instalación

1. Copiá la carpeta `MultiAccountExecutor` completa a
   `Documentos\NinjaTrader 8\bin\Custom\AddOns\`.
2. Abrí NinjaTrader 8 → **New** → **NinjaScript Editor** → **Tools** →
   **Compile** (F5). Los cinco archivos compilan juntos como parte del mismo
   assembly `Custom`.
3. Corregí los errores de compilación que aparezcan (ver sección siguiente:
   son los puntos más probables de fricción, específicos de tu versión de NT8).
4. Reiniciá NinjaTrader. Deberías ver **Control Center → New → Multi-Account
   Executor**.

## Puntos a verificar al compilar (lo más probable que necesite ajuste)

Estos son los lugares donde usé la API documentada de NinjaScript/Cbi de
memoria, sin poder validarla contra el compilador real. Si el editor tira
error ahí, es la firma exacta la que cambió entre builds de NT8, no la lógica:

- `Account.CreateOrder(...)` — el orden y tipos exactos de los parámetros
  (`MultiAccountExecutorEngine.LaunchDualEntry` / `PlaceBracket` / `ReplicateToFollowers`).
- `instrument.MarketData.Update` como evento de tick en vivo, y las
  propiedades de `MarketDataEventArgs` (`Price`, `Volume`, `Time`,
  `MarketDataType`) — en `MultiAccountExecutorWindow.OnMarketDataUpdate`.
- `Instrument.GetInstrument(string)` para resolver el instrumento desde el
  texto del panel — en `MultiAccountExecutorWindow.ApplyToEngine`. Si no
  encuentra el instrumento, puede necesitar una sobrecarga con un flag de
  "forzar búsqueda" según tu versión.
- El menú "New" del Control Center (`MenuItemNew`) en
  `MultiAccountExecutorAddOn.OnWindowCreated` — si no aparece el ítem, el
  nombre interno cambió; mientras tanto podés instanciar
  `new MultiAccountExecutorWindow().Show()` desde cualquier otro gancho
  (por ejemplo un botón temporal en un Indicator) para seguir probando el
  resto de la lógica sin depender del menú.
- `Account.DisplayName`, `Position.GetUnrealizedProfitLoss(...)`,
  `MasterInstrument.RoundToTickSize/PointValue/TickSize` — nombres estándar
  de Cbi, pero confirmalos si el compilador se queja.

Ninguno de estos afecta el diseño (replicación, break even, trailing,
límite diario): son ajustes de "nombre exacto de método/propiedad", no de
arquitectura.

## Cómo funciona la replicación multi-cuenta

1. La cuenta **maestra** es la única que recibe las dos órdenes stop de
   entrada (Buy Stop / Sell Stop) con el offset configurado.
2. Cuando **una** de esas dos llena, el motor cancela la otra (OCO
   compartido + cancelación defensiva manual como respaldo) y coloca el
   bracket TP/SL de la maestra.
3. En ese mismo instante, cada cuenta marcada como réplica recibe una
   **orden de mercado** en la misma dirección, con cantidad
   `round(cantidad_maestra × ratio_de_esa_cuenta)` (mínimo 1 contrato).
   Esto es "copiar el fill", no "copiar la orden pendiente": evita que una
   réplica dispare en una dirección distinta a la maestra por timing.
4. Cada cuenta (maestra y réplicas) gestiona **su propio** bracket, break
   even y trailing stop de forma independiente, porque cada una entra a un
   precio ligeramente distinto (spread/slippage de la orden de mercado vs.
   el stop de la maestra).
5. El límite de pérdida diaria también es por cuenta: si una réplica lo
   toca, esa cuenta deja de recibir nuevas réplicas (pero la maestra sigue
   operando). Si lo toca la **maestra**, se apaga el Master Switch general
   y no se generan nuevas entradas para nadie.

## Auto Volume Pro — interpretación

El anuncio original solo promete "detecta picos de volumen ... ejecuta
automáticamente con protección inmediata", sin especificar una regla
direccional. En vez de inventar una señal direccional sin base, un pico de
volumen acá simplemente **vuelve a armar el mismo bracket de entrada dual**
(stop arriba y abajo del precio actual): el volumen decide *cuándo* se arma
la trampa, el mercado decide *qué lado* se dispara, igual que en el resto
de la herramienta. Si tenés una regla direccional específica en mente (por
ejemplo, sesgo por delta de flujo de órdenes), se reemplaza fácil en
`MultiAccountExecutorEngine.OnVolumeTick`.

## "Leave open after TP"

En la v1 el TP cierra el 100% de la posición (bracket de cantidad completa),
así que este checkbox todavía no tiene efecto real — está en la UI para
reflejar el parámetro, pero falta implementar el cierre parcial (por
ejemplo, agregar un `PartialTpQuantity` y dividir la orden de target entre
"parte que cierra en TP" y "runner que sigue con trailing"). Decílo si lo
querés y lo sumo en una siguiente iteración.

## Próximos pasos posibles

- Cierre parcial real en TP + runner con trailing (activa "Leave open after TP").
- Panel de monitoreo por cuenta (hoy solo muestra el detalle de la maestra;
  el log de texto sí refleja fills de todas las cuentas).
- Persistir parámetros entre reinicios (hoy se resetean al reabrir la ventana).
- Reemplazar la señal de Auto Volume Pro por una regla direccional real si
  la tenés definida.
