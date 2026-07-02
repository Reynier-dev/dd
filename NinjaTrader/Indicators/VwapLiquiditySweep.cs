#region Using declarations
using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.ComponentModel.DataAnnotations;
using System.Windows.Media;
using System.Xml.Serialization;
using NinjaTrader.Cbi;
using NinjaTrader.Gui;
using NinjaTrader.Gui.Chart;
using NinjaTrader.Gui.SuperDom;
using NinjaTrader.Gui.Tools;
using NinjaTrader.Data;
using NinjaTrader.NinjaScript;
using NinjaTrader.Core.FloatingPoint;
using NinjaTrader.NinjaScript.DrawingTools;
#endregion

namespace NinjaTrader.NinjaScript.Indicators
{
	/// <summary>
	/// Session VWAP with standard-deviation bands plus liquidity-sweep detection.
	/// A sweep fires when price pierces a recent confirmed swing high/low and closes
	/// back inside it (stop hunt). Optionally requires the sweep to occur while price
	/// is extended away from VWAP (mean-reversion confluence).
	/// </summary>
	public class VwapLiquiditySweep : Indicator
	{
		private SessionIterator sessionIterator;

		private double sumSrcVol;
		private double sumSrcSrcVol;
		private double sumVol;

		private double lastSwingHigh = double.NaN;
		private double lastSwingLow  = double.NaN;

		protected override void OnStateChange()
		{
			if (State == State.SetDefaults)
			{
				Description					= @"VWAP with std-dev bands + liquidity sweep (stop hunt) detection.";
				Name						= "VwapLiquiditySweep";
				Calculate					= Calculate.OnEachTick;
				IsOverlay					= true;
				DisplayInDataBox			= true;
				DrawOnPricePanel			= true;
				PaintPriceMarkers			= true;
				ScaleJustification			= NinjaTrader.Gui.Chart.ScaleJustification.Right;
				IsSuspendedWhileInactive	= true;

				SwingStrength				= 5;
				UseVwapFilter				= true;
				FilterStdDevMultiplier		= 1.0;
				ShowSweepMarkers			= true;
				EnableAlerts				= false;

				AddPlot(new Stroke(Brushes.DodgerBlue, 2), PlotStyle.Line, "Vwap");
				AddPlot(new Stroke(Brushes.DarkGray, DashStyleHelper.Dash, 1), PlotStyle.Line, "UpperBand1");
				AddPlot(new Stroke(Brushes.DarkGray, DashStyleHelper.Dash, 1), PlotStyle.Line, "LowerBand1");
				AddPlot(new Stroke(Brushes.DimGray, DashStyleHelper.Dot, 1), PlotStyle.Line, "UpperBand2");
				AddPlot(new Stroke(Brushes.DimGray, DashStyleHelper.Dot, 1), PlotStyle.Line, "LowerBand2");
			}
			else if (State == State.DataLoaded)
			{
				sessionIterator = new SessionIterator(Bars);
			}
		}

		protected override void OnBarUpdate()
		{
			if (BarsInProgress != 0)
				return;

			if (CurrentBar < 1)
				return;

			// --- VWAP (resets every new session) ---
			if (sessionIterator.IsNewSession(Time[0], IsFirstTickOfBar))
			{
				sessionIterator.GetNextSession(Time[0], IsFirstTickOfBar);
				sumSrcVol		= 0;
				sumSrcSrcVol	= 0;
				sumVol			= 0;
			}

			double src = (High[0] + Low[0] + Close[0]) / 3.0;
			double vol = Math.Max(Volume[0], 0);

			sumSrcVol		+= src * vol;
			sumSrcSrcVol	+= src * src * vol;
			sumVol			+= vol;

			double vwap = sumVol > 0 ? sumSrcVol / sumVol : src;
			double variance = sumVol > 0 ? Math.Max((sumSrcSrcVol / sumVol) - (vwap * vwap), 0) : 0;
			double stdDev = Math.Sqrt(variance);

			Vwap[0]			= vwap;
			UpperBand1[0]	= vwap + stdDev;
			LowerBand1[0]	= vwap - stdDev;
			UpperBand2[0]	= vwap + 2 * stdDev;
			LowerBand2[0]	= vwap - 2 * stdDev;

			// --- Confirm swing highs/lows (fractal, lags SwingStrength bars) ---
			if (CurrentBar >= SwingStrength * 2)
			{
				int pivot = SwingStrength;
				bool isSwingHigh = true;
				bool isSwingLow  = true;
				double pivotHigh = High[pivot];
				double pivotLow  = Low[pivot];

				for (int j = 1; j <= SwingStrength; j++)
				{
					if (High[pivot - j] > pivotHigh || High[pivot + j] > pivotHigh)
						isSwingHigh = false;
					if (Low[pivot - j] < pivotLow || Low[pivot + j] < pivotLow)
						isSwingLow = false;
				}

				if (isSwingHigh)
					lastSwingHigh = pivotHigh;
				if (isSwingLow)
					lastSwingLow = pivotLow;
			}

			// --- Liquidity sweep detection on the current bar ---
			bool bearishSweep = !double.IsNaN(lastSwingHigh) && High[0] > lastSwingHigh && Close[0] < lastSwingHigh;
			bool bullishSweep = !double.IsNaN(lastSwingLow)  && Low[0]  < lastSwingLow  && Close[0] > lastSwingLow;

			if (UseVwapFilter)
			{
				double threshold = FilterStdDevMultiplier * stdDev;
				bearishSweep = bearishSweep && High[0] >= vwap + threshold;
				bullishSweep = bullishSweep && Low[0]  <= vwap - threshold;
			}

			if (bearishSweep)
			{
				// Once a swing high is swept it's no longer a valid untapped liquidity level.
				lastSwingHigh = double.NaN;

				if (ShowSweepMarkers)
					Draw.TriangleDown(this, "BearSweep" + CurrentBar, false, 0, High[0] + 2 * TickSize, Brushes.Crimson);

				if (EnableAlerts)
					Alert("BearSweep" + CurrentBar, Priority.High, "VwapLiquiditySweep: bearish liquidity sweep on " + Instrument.FullName, string.Empty, 10, Brushes.Transparent, Brushes.Crimson);
			}

			if (bullishSweep)
			{
				lastSwingLow = double.NaN;

				if (ShowSweepMarkers)
					Draw.TriangleUp(this, "BullSweep" + CurrentBar, false, 0, Low[0] - 2 * TickSize, Brushes.SeaGreen);

				if (EnableAlerts)
					Alert("BullSweep" + CurrentBar, Priority.High, "VwapLiquiditySweep: bullish liquidity sweep on " + Instrument.FullName, string.Empty, 10, Brushes.Transparent, Brushes.SeaGreen);
			}
		}

		#region Properties
		[NinjaScriptProperty]
		[Range(1, 50)]
		[Display(Name = "Swing Strength", Description = "Bars required on each side to confirm a swing high/low.", Order = 1, GroupName = "Liquidity")]
		public int SwingStrength { get; set; }

		[NinjaScriptProperty]
		[Display(Name = "Use VWAP Filter", Description = "Only flag a sweep when price is extended from VWAP.", Order = 2, GroupName = "Liquidity")]
		public bool UseVwapFilter { get; set; }

		[NinjaScriptProperty]
		[Range(0.0, 10.0)]
		[Display(Name = "Filter Std-Dev Multiplier", Description = "How far (in std-devs) price must be from VWAP for a sweep to count.", Order = 3, GroupName = "Liquidity")]
		public double FilterStdDevMultiplier { get; set; }

		[NinjaScriptProperty]
		[Display(Name = "Show Sweep Markers", Description = "Draw triangle markers on the chart at sweep bars.", Order = 4, GroupName = "Liquidity")]
		public bool ShowSweepMarkers { get; set; }

		[NinjaScriptProperty]
		[Display(Name = "Enable Alerts", Description = "Fire a NinjaTrader alert when a sweep is detected.", Order = 5, GroupName = "Liquidity")]
		public bool EnableAlerts { get; set; }

		[Browsable(false)]
		[XmlIgnore]
		public Series<double> Vwap
		{
			get { return Values[0]; }
		}

		[Browsable(false)]
		[XmlIgnore]
		public Series<double> UpperBand1
		{
			get { return Values[1]; }
		}

		[Browsable(false)]
		[XmlIgnore]
		public Series<double> LowerBand1
		{
			get { return Values[2]; }
		}

		[Browsable(false)]
		[XmlIgnore]
		public Series<double> UpperBand2
		{
			get { return Values[3]; }
		}

		[Browsable(false)]
		[XmlIgnore]
		public Series<double> LowerBand2
		{
			get { return Values[4]; }
		}
		#endregion
	}
}

#region NinjaScript generated code. Neither change nor remove.

namespace NinjaTrader.NinjaScript.Indicators
{
	public partial class Indicator : NinjaTrader.Gui.NinjaScript.IndicatorRenderBase
	{
		private VwapLiquiditySweep[] cacheVwapLiquiditySweep;
		public VwapLiquiditySweep VwapLiquiditySweep(int swingStrength, bool useVwapFilter, double filterStdDevMultiplier, bool showSweepMarkers, bool enableAlerts)
		{
			return VwapLiquiditySweep(Input, swingStrength, useVwapFilter, filterStdDevMultiplier, showSweepMarkers, enableAlerts);
		}

		public VwapLiquiditySweep VwapLiquiditySweep(ISeries<double> input, int swingStrength, bool useVwapFilter, double filterStdDevMultiplier, bool showSweepMarkers, bool enableAlerts)
		{
			if (cacheVwapLiquiditySweep != null)
				for (int idx = 0; idx < cacheVwapLiquiditySweep.Length; idx++)
					if (cacheVwapLiquiditySweep[idx] != null && cacheVwapLiquiditySweep[idx].SwingStrength == swingStrength && cacheVwapLiquiditySweep[idx].UseVwapFilter == useVwapFilter && cacheVwapLiquiditySweep[idx].FilterStdDevMultiplier == filterStdDevMultiplier && cacheVwapLiquiditySweep[idx].ShowSweepMarkers == showSweepMarkers && cacheVwapLiquiditySweep[idx].EnableAlerts == enableAlerts && cacheVwapLiquiditySweep[idx].EqualsInput(input))
						return cacheVwapLiquiditySweep[idx];

			return CacheIndicator<VwapLiquiditySweep>(new VwapLiquiditySweep(){ SwingStrength = swingStrength, UseVwapFilter = useVwapFilter, FilterStdDevMultiplier = filterStdDevMultiplier, ShowSweepMarkers = showSweepMarkers, EnableAlerts = enableAlerts }, input, ref cacheVwapLiquiditySweep);
		}
	}
}

namespace NinjaTrader.NinjaScript.MarketAnalyzerColumns
{
	public partial class MarketAnalyzerColumn : MarketAnalyzerColumnBase
	{
		public Indicators.VwapLiquiditySweep VwapLiquiditySweep(int swingStrength, bool useVwapFilter, double filterStdDevMultiplier, bool showSweepMarkers, bool enableAlerts)
		{
			return indicator.VwapLiquiditySweep(Input, swingStrength, useVwapFilter, filterStdDevMultiplier, showSweepMarkers, enableAlerts);
		}

		public Indicators.VwapLiquiditySweep VwapLiquiditySweep(ISeries<double> input , int swingStrength, bool useVwapFilter, double filterStdDevMultiplier, bool showSweepMarkers, bool enableAlerts)
		{
			return indicator.VwapLiquiditySweep(input, swingStrength, useVwapFilter, filterStdDevMultiplier, showSweepMarkers, enableAlerts);
		}
	}
}

namespace NinjaTrader.NinjaScript.Strategies
{
	public partial class Strategy : NinjaTrader.Gui.NinjaScript.StrategyRenderBase
	{
		public Indicators.VwapLiquiditySweep VwapLiquiditySweep(int swingStrength, bool useVwapFilter, double filterStdDevMultiplier, bool showSweepMarkers, bool enableAlerts)
		{
			return indicator.VwapLiquiditySweep(Input, swingStrength, useVwapFilter, filterStdDevMultiplier, showSweepMarkers, enableAlerts);
		}

		public Indicators.VwapLiquiditySweep VwapLiquiditySweep(ISeries<double> input , int swingStrength, bool useVwapFilter, double filterStdDevMultiplier, bool showSweepMarkers, bool enableAlerts)
		{
			return indicator.VwapLiquiditySweep(input, swingStrength, useVwapFilter, filterStdDevMultiplier, showSweepMarkers, enableAlerts);
		}
	}
}

#endregion
