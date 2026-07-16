#region Using declarations
using NinjaTrader.Cbi;
#endregion

namespace NinjaTrader.NinjaScript.AddOns.MultiAccountExecutor
{
	/// <summary>
	/// Per-account working state: pending entry orders, bracket orders and today's risk usage
	/// for one account (the master or one of its replicas).
	/// </summary>
	public class AccountSlot
	{
		public Account Account { get; }
		public bool IsMaster { get; }

		/// <summary>Replica-only. Whether this account currently mirrors the master's fills.</summary>
		public bool ReplicateEnabled { get; set; } = true;

		/// <summary>Replica-only. Quantity sent to this account = Round(masterFillQty * QuantityRatio), min 1.</summary>
		public double QuantityRatio { get; set; } = 1.0;

		public Order BuyStopEntry;
		public Order SellStopEntry;
		public Order StopLossOrder;
		public Order TargetOrder;

		public MarketPosition Direction = MarketPosition.Flat;
		public int Quantity;
		public double AverageEntryPrice;
		public double TrailingExtremePrice;
		public bool BreakEvenApplied;

		public double SessionStartRealized;
		public bool DailyLimitHit;

		/// <summary>Realized $ of the most recently closed trade (set on TP/SL fill, kept until the next one).</summary>
		public double LastTradeRealizedPnL;

		public AccountSlot(Account account, bool isMaster)
		{
			Account = account;
			IsMaster = isMaster;
		}

		public bool IsFlat => Direction == MarketPosition.Flat;

		public void ResetTradeState()
		{
			BuyStopEntry = null;
			SellStopEntry = null;
			StopLossOrder = null;
			TargetOrder = null;
			Direction = MarketPosition.Flat;
			Quantity = 0;
			AverageEntryPrice = 0;
			TrailingExtremePrice = 0;
			BreakEvenApplied = false;
		}
	}
}
