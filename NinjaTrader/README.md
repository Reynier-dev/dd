# VWAP + Toma de Liquidez — Indicador para NinjaTrader 8

`Indicators/VwapLiquiditySweep.cs` es un **Indicator** de NinjaScript (no ejecuta órdenes) que combina:

1. **VWAP de sesión** con bandas de desviación estándar (1σ y 2σ), reiniciado en cada nueva sesión.
2. **Detección de barridos de liquidez** (liquidity sweeps / stop hunts): identifica swing highs/lows confirmados (fractal simple, configurable en cantidad de barras) y marca cuando el precio los perfora con la mecha pero cierra de vuelta adentro — señal clásica de "toma de stops" antes de revertir.
3. **Filtro de confluencia con VWAP** (opcional): solo considera válido un barrido si ocurre mientras el precio está extendido X desviaciones estándar respecto al VWAP, para priorizar reversiones con "combustible" real en vez de ruido.

## Lógica de señales

- **Barrido bajista (🔻 triángulo rojo)**: el precio perfora un swing high reciente (`High[0] > lastSwingHigh`) pero cierra por debajo (`Close[0] < lastSwingHigh`). Si el filtro VWAP está activo, además exige que el máximo esté por encima de `VWAP + N·σ`. Es una señal de posible reversión bajista.
- **Barrido alcista (🔺 triángulo verde)**: análogo con swing low, mecha perfora hacia abajo y cierra de vuelta adentro, con el mínimo por debajo de `VWAP - N·σ` si el filtro está activo. Señal de posible reversión alcista.

Una vez que un nivel es barrido, se invalida (`lastSwingHigh`/`lastSwingLow` se resetea) para no repetir señales sobre el mismo nivel.

## Parámetros

| Parámetro | Default | Descripción |
|---|---|---|
| Swing Strength | 5 | Barras a cada lado requeridas para confirmar un swing high/low. Más alto = niveles más significativos pero con más rezago. |
| Use VWAP Filter | true | Exige que el barrido ocurra lejos del VWAP para contar como señal. |
| Filter Std-Dev Multiplier | 1.0 | Cuántas desviaciones estándar de distancia al VWAP se exigen si el filtro está activo. |
| Show Sweep Markers | true | Dibuja los triángulos en el gráfico. |
| Enable Alerts | false | Dispara una alerta de NinjaTrader (sin sonido por defecto) cuando se detecta un barrido. |

## Instalación en NinjaTrader 8

1. Abrí NinjaTrader 8 → **New** → **NinjaScript Editor**.
2. Click derecho sobre `Indicators` → **New Indicator...** (o `Tools` → `Import` → `NinjaScript Add-On` si preferís importarlo como archivo).
3. Pegá el contenido de `VwapLiquiditySweep.cs` reemplazando el template generado (o copiá el archivo directamente a `Documentos\NinjaTrader 8\bin\Custom\Indicators\` y compilá con F5 desde el Editor).
4. Compilá (F5). Debería compilar sin errores.
5. En un gráfico: click derecho → **Indicators...** → buscar `VwapLiquiditySweep` → agregar y ajustar parámetros.

## Próximos pasos posibles

- Convertir esta lógica en una **Strategy** con `EnterLong`/`EnterShort`, stop detrás del extremo del barrido y target en VWAP o banda opuesta.
- Anclar el VWAP a un evento (apertura de rango, swing point) en vez de reiniciarlo por sesión (Anchored VWAP).
- Agregar filtro de sesión horaria (ej. solo operar en RTH) y filtro de volumen mínimo en la vela del barrido.

---

# Swing diario EMA 200 + RSI(2) — `Indicators/EmaRsiSwing.cs`

Indicador (no ejecuta órdenes) con el único setup EMA/RSI que pasó todas las pruebas del estudio de 15 años en [`research/ema_rsi/REPORT.md`](../research/ema_rsi/REPORT.md): comprar la sobreventa de corto plazo solo a favor de la tendencia mayor. **Solo largos. Para gráficos diarios** (en otro timeframe muestra un aviso y no calcula).

## Lógica

1. **Bias:** el cierre diario tiene que estar sobre la **EMA 200** (línea violeta).
2. **Señal:** el **RSI(2)** cierra por debajo de `RSI(2) Entry Level` (10). Flecha verde: comprar en la **apertura de la sesión siguiente**.
3. **Stop:** `Stop (ATR multiple)` × ATR(14) de la vela de señal, medido desde la apertura de entrada. Se dibuja como marcas rojas mientras la operación está abierta.
4. **Salida:** rombo gris en el primer cierre por encima de la **EMA 5** (línea dorada) → vender en la apertura siguiente. Rombo naranja si tocó el stop. Si pasan `Max Bars In Trade` sesiones (20), salida al cierre.

Mientras hay una operación abierta no se dibujan señales nuevas. En la esquina superior derecha se muestra el RSI(2), si el precio está sobre la EMA 200 y el estado de la operación (fecha de entrada, stop, nivel de salida).

En el backtest 2005–2020 esta lógica dio en NQ 73% de aciertos y +0,15R por operación, en ES 75% y +0,11R, en RTY 70% y +0,06R, con ~9 operaciones al año por índice y 3–4 días por operación. No funciona en petróleo. Una emulación vela por vela de este archivo reproduce el backtest operación por operación.

## Parámetros

| Parámetro | Default | Descripción |
|---|---|---|
| RSI(2) Entry Level | 10 | Umbral de sobreventa del RSI(2). Del 5 al 25 todas las variantes fueron positivas en índices; 10 fue la mejor. |
| Stop (ATR multiple) | 2.0 | Distancia del stop en ATR(14) diarios desde la apertura de entrada. |
| Max Bars In Trade | 20 | Salida por tiempo, en sesiones desde la señal. |
| Show Info Panel / Enable Alerts | true / false | Panel de estado y alertas de NinjaTrader en cada señal y salida. |

Para usarlo desde una Strategy, el indicador expone `Signal` (1 en la vela de señal), `InTrade` (1 mientras la operación sigue abierta) y `StopLevel`.

## Requisitos del gráfico

- **Gráfico diario** con al menos **250 sesiones** cargadas (la EMA 200 necesita ~200 para estabilizarse).
- NQ, ES o RTY (o sus micros MNQ/MES/M2K). Operar la misma señal en NQ y ES a la vez no diversifica: se mueven un 93% igual en diario.

La instalación es igual a la del indicador VWAP: copiar el `.cs` a `Documentos\NinjaTrader 8\bin\Custom\Indicators\` y compilar con F5 desde el NinjaScript Editor. **Este archivo no se compiló en el entorno donde se escribió** (no hay NinjaTrader disponible; se verificó su sintaxis y se emuló su lógica en Python). Si el editor marca algún error, avisame con el mensaje exacto.
