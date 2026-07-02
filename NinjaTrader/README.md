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
