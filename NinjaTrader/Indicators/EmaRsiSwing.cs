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
	/// Daily swing setup that survived the study in research/ema_rsi: buy the close-to-close
	/// oversold dip (RSI(2) below EntryLevel) only while the close is above the EMA 200, and
	/// exit on the first close above the EMA 5. Entries and exits are meant to be executed at
	/// the next session's open; the protective stop is StopAtrMultiplier x ATR(14) from that
	/// open. Long only. For DAILY charts. It only marks the trades, it does not place orders.
	/// </summary>
	public class EmaRsiSwing : Indicator
	{
		private const int TrendPeriod	= 200;
		private const int ExitPeriod	= 5;
		private const int RsiPeriod		= 2;
		private const int AtrPeriod		= 14;

		private EMA emaTrend;
		private EMA emaExit;
		private RSI rsi;
		private ATR atr;

		// 0 = flat, 1 = signal fired, entry pending at next open, 2 = in trade
		private int state;
		private int signalBar;
		private double signalAtr;
		private double entryPrice;
		private double stopPrice;

		private Series<double> signal;
		private Series<double> inTrade;

		protected override void OnStateChange()
		{
			if (State == State.SetDefaults)
			{
				Description					= @"Daily swing: RSI(2) oversold above EMA 200, exit on close above EMA 5, ATR stop. Long only, daily charts.";
				Name						= "EmaRsiSwing";
				Calculate					= Calculate.OnBarClose;
				IsOverlay					= true;
				DisplayInDataBox			= true;
				DrawOnPricePanel			= true;
				PaintPriceMarkers			= true;
				ScaleJustification			= NinjaTrader.Gui.Chart.ScaleJustification.Right;
				IsSuspendedWhileInactive	= false;

				EntryLevel					= 10;
				StopAtrMultiplier			= 2.0;
				MaxBarsInTrade				= 20;
				ShowInfoPanel				= true;
				EnableAlerts				= false;

				AddPlot(new Stroke(Brushes.MediumPurple, 2), PlotStyle.Line, "Ema200");
				AddPlot(new Stroke(Brushes.Goldenrod, 1), PlotStyle.Line, "Ema5");
				AddPlot(new Stroke(Brushes.Crimson, 2), PlotStyle.Hash, "StopLevel");
			}
			else if (State == State.DataLoaded)
			{
				emaTrend	= EMA(Close, TrendPeriod);
				emaExit		= EMA(Close, ExitPeriod);
				rsi			= RSI(Close, RsiPeriod, 1);
				atr			= ATR(AtrPeriod);
				signal		= new Series<double>(this);
				inTrade		= new Series<double>(this);
				state		= 0;
			}
		}

		protected override void OnBarUpdate()
		{
			if (BarsPeriod.BarsPeriodType != BarsPeriodType.Day)
			{
				Draw.TextFixed(this, "EmaRsiSwingInfo", "EmaRsiSwing: use it on a DAILY chart", TextPosition.TopRight);
				return;
			}

			Ema200[0]	= emaTrend[0];
			Ema5[0]		= emaExit[0];
			signal[0]	= 0;
			inTrade[0]	= 0;

			if (CurrentBar < TrendPeriod)
				return;

			// The bar after a signal: the trade is opened at this bar's open.
			if (state == 1)
			{
				state		= 2;
				entryPrice	= Open[0];
				stopPrice	= Instrument.MasterInstrument.RoundToTickSize(entryPrice - StopAtrMultiplier * signalAtr);
			}

			bool exitedOnSignal = false;
			if (state == 2)
				exitedOnSignal = ManageTrade();

			if (state == 0 && !exitedOnSignal && Close[0] > emaTrend[0] && rsi[0] < EntryLevel)
			{
				state		= 1;
				signalBar	= CurrentBar;
				signalAtr	= atr[0];
				signal[0]	= 1;
				Draw.ArrowUp(this, "SwingEntry" + CurrentBar, false, 0, Low[0] - 2 * TickSize, Brushes.SeaGreen);

				if (EnableAlerts)
					Alert("SwingEntry" + CurrentBar, Priority.High,
						string.Format("EmaRsiSwing: BUY {0} at next open, RSI(2) {1:0.0}", Instrument.FullName, rsi[0]),
						string.Empty, 10, Brushes.Transparent, Brushes.SeaGreen);
			}

			if (ShowInfoPanel)
				Draw.TextFixed(this, "EmaRsiSwingInfo", InfoText(), TextPosition.TopRight);
		}

		// Returns true when the trade ends on the exit signal (executed at the next open),
		// in which case the backtest does not allow a new signal on this same bar.
		private bool ManageTrade()
		{
			bool firstBar = CurrentBar == signalBar + 1;
			double exitPrice;
			string reason;
			bool onSignal = false;

			if (Low[0] <= stopPrice)
			{
				// A gap through the stop fills at the open, except on the entry bar itself.
				exitPrice	= firstBar ? stopPrice : Math.Min(Open[0], stopPrice);
				reason		= "stop";
			}
			else if (CurrentBar - signalBar >= MaxBarsInTrade)
			{
				exitPrice	= Close[0];
				reason		= "time limit";
			}
			else if (Close[0] > emaExit[0])
			{
				exitPrice	= Close[0];
				reason		= "close above EMA 5, sell at next open";
				onSignal	= true;
			}
			else
			{
				StopLevel[0]	= stopPrice;
				inTrade[0]	= 1;
				return false;
			}

			StopLevel[0] = stopPrice;
			Draw.Diamond(this, "SwingExit" + CurrentBar, false, 0, exitPrice, reason == "stop" ? Brushes.DarkOrange : Brushes.Gray);

			if (EnableAlerts)
				Alert("SwingExit" + CurrentBar, Priority.Medium,
					string.Format("EmaRsiSwing: EXIT {0} ({1})", Instrument.FullName, reason),
					string.Empty, 10, Brushes.Transparent, Brushes.Gray);

			state = 0;
			return onSignal;
		}

		private string InfoText()
		{
			string trend = Close[0] > emaTrend[0] ? "above EMA 200" : "below EMA 200 (no longs)";
			string status;
			if (state == 1)
				status = "SIGNAL: buy at next open";
			else if (state == 2)
				status = string.Format("In trade since {0:d}, stop {1}, exit on close > {2}",
					Time[CurrentBar - signalBar - 1], Instrument.MasterInstrument.FormatPrice(stopPrice),
					Instrument.MasterInstrument.FormatPrice(emaExit[0]));
			else
				status = string.Format("Flat. Signal when RSI(2) < {0} with close above EMA 200", EntryLevel);
			return string.Format("RSI(2): {0:0.0}   Close {1}\n{2}", rsi[0], trend, status);
		}

		#region Properties
		[NinjaScriptProperty]
		[Range(1, 50)]
		[Display(Name = "RSI(2) Entry Level", Description = "Signal when RSI(2) closes below this level with the close above the EMA 200.", Order = 1, GroupName = "Signals")]
		public int EntryLevel { get; set; }

		[NinjaScriptProperty]
		[Range(0.5, 10.0)]
		[Display(Name = "Stop (ATR multiple)", Description = "Protective stop distance from the entry open, in ATR(14) of the signal bar.", Order = 2, GroupName = "Signals")]
		public double StopAtrMultiplier { get; set; }

		[NinjaScriptProperty]
		[Range(1, 200)]
		[Display(Name = "Max Bars In Trade", Description = "Exit at the close once this many sessions have passed since the signal.", Order = 3, GroupName = "Signals")]
		public int MaxBarsInTrade { get; set; }

		[Display(Name = "Show Info Panel", Description = "Show RSI(2), trend and trade status in the top-right corner.", Order = 4, GroupName = "Display")]
		public bool ShowInfoPanel { get; set; }

		[Display(Name = "Enable Alerts", Description = "Fire a NinjaTrader alert on every signal and exit.", Order = 5, GroupName = "Display")]
		public bool EnableAlerts { get; set; }

		[Browsable(false)]
		[XmlIgnore]
		public Series<double> Ema200
		{
			get { return Values[0]; }
		}

		[Browsable(false)]
		[XmlIgnore]
		public Series<double> Ema5
		{
			get { return Values[1]; }
		}

		[Browsable(false)]
		[XmlIgnore]
		public Series<double> StopLevel
		{
			get { return Values[2]; }
		}

		/// <summary>1 on the bar where a buy signal fires (execute at the next open), 0 otherwise.</summary>
		[Browsable(false)]
		[XmlIgnore]
		public Series<double> Signal
		{
			get { return signal; }
		}

		/// <summary>1 while a trade is open after this bar's close, 0 otherwise.</summary>
		[Browsable(false)]
		[XmlIgnore]
		public Series<double> InTrade
		{
			get { return inTrade; }
		}
		#endregion
	}
}

#region NinjaScript generated code. Neither change nor remove.

namespace NinjaTrader.NinjaScript.Indicators
{
	public partial class Indicator : NinjaTrader.Gui.NinjaScript.IndicatorRenderBase
	{
		private EmaRsiSwing[] cacheEmaRsiSwing;
		public EmaRsiSwing EmaRsiSwing(int entryLevel, double stopAtrMultiplier, int maxBarsInTrade)
		{
			return EmaRsiSwing(Input, entryLevel, stopAtrMultiplier, maxBarsInTrade);
		}

		public EmaRsiSwing EmaRsiSwing(ISeries<double> input, int entryLevel, double stopAtrMultiplier, int maxBarsInTrade)
		{
			if (cacheEmaRsiSwing != null)
				for (int idx = 0; idx < cacheEmaRsiSwing.Length; idx++)
					if (cacheEmaRsiSwing[idx] != null && cacheEmaRsiSwing[idx].EntryLevel == entryLevel && cacheEmaRsiSwing[idx].StopAtrMultiplier == stopAtrMultiplier && cacheEmaRsiSwing[idx].MaxBarsInTrade == maxBarsInTrade && cacheEmaRsiSwing[idx].EqualsInput(input))
						return cacheEmaRsiSwing[idx];

			return CacheIndicator<EmaRsiSwing>(new EmaRsiSwing(){ EntryLevel = entryLevel, StopAtrMultiplier = stopAtrMultiplier, MaxBarsInTrade = maxBarsInTrade }, input, ref cacheEmaRsiSwing);
		}
	}
}

namespace NinjaTrader.NinjaScript.MarketAnalyzerColumns
{
	public partial class MarketAnalyzerColumn : MarketAnalyzerColumnBase
	{
		public Indicators.EmaRsiSwing EmaRsiSwing(int entryLevel, double stopAtrMultiplier, int maxBarsInTrade)
		{
			return indicator.EmaRsiSwing(Input, entryLevel, stopAtrMultiplier, maxBarsInTrade);
		}

		public Indicators.EmaRsiSwing EmaRsiSwing(ISeries<double> input , int entryLevel, double stopAtrMultiplier, int maxBarsInTrade)
		{
			return indicator.EmaRsiSwing(input, entryLevel, stopAtrMultiplier, maxBarsInTrade);
		}
	}
}

namespace NinjaTrader.NinjaScript.Strategies
{
	public partial class Strategy : NinjaTrader.Gui.NinjaScript.StrategyRenderBase
	{
		public Indicators.EmaRsiSwing EmaRsiSwing(int entryLevel, double stopAtrMultiplier, int maxBarsInTrade)
		{
			return indicator.EmaRsiSwing(Input, entryLevel, stopAtrMultiplier, maxBarsInTrade);
		}

		public Indicators.EmaRsiSwing EmaRsiSwing(ISeries<double> input , int entryLevel, double stopAtrMultiplier, int maxBarsInTrade)
		{
			return indicator.EmaRsiSwing(input, entryLevel, stopAtrMultiplier, maxBarsInTrade);
		}
	}
}

#endregion
