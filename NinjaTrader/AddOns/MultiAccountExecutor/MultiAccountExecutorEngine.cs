#region Using declarations
using System;
using System.Collections.Generic;
using System.Linq;
using NinjaTrader.Cbi;
#endregion

namespace NinjaTrader.NinjaScript.AddOns.MultiAccountExecutor
{
	public enum CycleState
	{
		Idle,
		PendingEntries,
		InPosition,
		Flattening
	}

	/// <summary>
	/// Order routing, replication and risk engine. Deliberately free of UI code so it can be
	/// driven (and eventually unit-exercised) independently of the WPF window.
	///
	/// Order model: unmanaged orders via Account.CreateOrder/Submit/Change/Cancel. AddOns are not
	/// bound to a single Strategy instance, and this engine routes orders across several accounts
	/// at once, so the managed EnterLong/SetStopLoss API (Strategy-only) does not fit here.
	///
	/// Replication model: the master account works the dual stop-entry bracket. Replica accounts
	/// do NOT get their own independent resting entry orders (that could fill at different prices
	/// or trigger only on one side) -- instead, the moment the master's entry fills, each replica
	/// receives a market order mirroring the master's direction and a size scaled by its own
	/// QuantityRatio. This is the standard "trade copier" pattern and keeps every account's
	/// position in sync with the master's actual fill instead of an independently-timed entry.
	/// </summary>
	public class MultiAccountExecutorEngine
	{
		public Instrument Instrument { get; set; }
		public ExecutionParameters Parameters { get; set; } = new ExecutionParameters();
		public List<AccountSlot> Slots { get; } = new List<AccountSlot>();
		public CycleState State { get; private set; } = CycleState.Idle;
		public bool MasterSwitchOn { get; set; }

		public event Action<string> Log = delegate { };
		public event Action Changed = delegate { };

		private DateTime lastEntryDate = DateTime.MinValue;
		private DateTime lastVolumeSignalTime = DateTime.MinValue;
		private double bucketVolume;
		private DateTime bucketStart = DateTime.MinValue;
		private readonly Queue<double> recentBucketVolumes = new Queue<double>();
		private double lastCumulativeVolume = double.NaN;

		public AccountSlot Master => Slots.FirstOrDefault(s => s.IsMaster);

		public void AttachAccount(Account account, bool isMaster)
		{
			if (Slots.Any(s => s.Account == account))
				return;

			var slot = new AccountSlot(account, isMaster);
			account.OrderUpdate += OnOrderUpdate;
			account.ExecutionUpdate += OnExecutionUpdate;
			Slots.Add(slot);
		}

		public void DetachAll()
		{
			foreach (var slot in Slots)
			{
				slot.Account.OrderUpdate -= OnOrderUpdate;
				slot.Account.ExecutionUpdate -= OnExecutionUpdate;
			}
			Slots.Clear();
		}

		private double TickSize => Instrument.MasterInstrument.TickSize;

		// ---------------------------------------------------------------
		// Entry
		// ---------------------------------------------------------------

		/// <summary>Places the buy-stop/sell-stop bracket on the master account only.</summary>
		public void LaunchDualEntry()
		{
			var master = Master;
			if (master == null || Instrument == null)
			{
				Log("No hay cuenta maestra o instrumento configurado.");
				return;
			}

			if (master.DailyLimitHit)
			{
				Log("Límite de pérdida diaria alcanzado en la cuenta maestra: entrada bloqueada.");
				return;
			}

			if (State != CycleState.Idle)
			{
				Log("Ya hay una entrada u operación en curso; se ignora Launch.");
				return;
			}

			double last = Instrument.MarketData?.Last?.Price ?? 0;
			if (last <= 0)
			{
				Log("Sin precio de mercado disponible todavía.");
				return;
			}

			string ocoId = "MAE-" + Guid.NewGuid().ToString("N").Substring(0, 8);
			double buyStopPrice = RoundToTick(last + Parameters.OffsetTicks * TickSize);
			double sellStopPrice = RoundToTick(last - Parameters.OffsetTicks * TickSize);

			master.BuyStopEntry = master.Account.CreateOrder(Instrument, OrderAction.Buy, OrderType.StopMarket,
				OrderEntry.Manual, TimeInForce.Day, Parameters.EntryContracts, 0, buyStopPrice, ocoId,
				"MAE-BuyEntry", Core.Globals.MaxDate, null);

			master.SellStopEntry = master.Account.CreateOrder(Instrument, OrderAction.SellShort, OrderType.StopMarket,
				OrderEntry.Manual, TimeInForce.Day, Parameters.EntryContracts, 0, sellStopPrice, ocoId,
				"MAE-SellEntry", Core.Globals.MaxDate, null);

			master.Account.Submit(new[] { master.BuyStopEntry, master.SellStopEntry });

			State = CycleState.PendingEntries;
			lastEntryDate = Core.Globals.Now.Date;
			Log($"Entrada dual enviada: BuyStop {buyStopPrice:0.00} / SellStop {sellStopPrice:0.00} x{Parameters.EntryContracts}");
			Changed();
		}

		// ---------------------------------------------------------------
		// Order / execution events
		// ---------------------------------------------------------------

		private void OnOrderUpdate(object sender, OrderEventArgs e)
		{
			var slot = Slots.FirstOrDefault(s => s.Account == e.Order.Account);
			if (slot == null)
				return;

			// Defensive OCO: if the sim/exchange didn't auto-cancel the sibling entry via the
			// shared oco id, cancel it ourselves so we never end up with both sides filling.
			if (slot.IsMaster && e.Order.OrderState == OrderState.Filled)
			{
				if (e.Order == slot.BuyStopEntry && slot.SellStopEntry != null && IsCancelable(slot.SellStopEntry))
					slot.Account.Cancel(new[] { slot.SellStopEntry });
				else if (e.Order == slot.SellStopEntry && slot.BuyStopEntry != null && IsCancelable(slot.BuyStopEntry))
					slot.Account.Cancel(new[] { slot.BuyStopEntry });
			}

			Changed();
		}

		private static bool IsCancelable(Order order)
		{
			return order.OrderState == OrderState.Working || order.OrderState == OrderState.Accepted
				|| order.OrderState == OrderState.PendingChange;
		}

		private void OnExecutionUpdate(object sender, ExecutionEventArgs e)
		{
			var slot = Slots.FirstOrDefault(s => s.Account == e.Execution.Account);
			if (slot == null)
				return;

			var order = e.Execution.Order;

			bool isMasterEntryFill = slot.IsMaster && (order == slot.BuyStopEntry || order == slot.SellStopEntry);
			bool isReplicaEntryFill = !slot.IsMaster && order != null && order.Name == "MAE-ReplicaEntry";

			if (isMasterEntryFill || isReplicaEntryFill)
			{
				OnEntryFilled(slot, e.Execution);
				return;
			}

			bool isStopFill = order == slot.StopLossOrder;
			bool isTargetFill = order == slot.TargetOrder;

			if (isStopFill || isTargetFill)
				OnExitFilled(slot, isTargetFill, e.Execution);
		}

		private void OnEntryFilled(AccountSlot slot, Execution execution)
		{
			slot.Direction = execution.MarketPosition;
			slot.Quantity = execution.Quantity;
			slot.AverageEntryPrice = execution.Price;
			slot.TrailingExtremePrice = execution.Price;
			slot.BreakEvenApplied = false;

			PlaceBracket(slot);

			if (slot.IsMaster)
			{
				State = CycleState.InPosition;
				ReplicateToFollowers(slot);
			}

			Log($"{AccountLabel(slot)}: entrada llena {slot.Direction} x{slot.Quantity} @ {slot.AverageEntryPrice:0.00}");
			Changed();
		}

		private void PlaceBracket(AccountSlot slot)
		{
			bool isLong = slot.Direction == MarketPosition.Long;
			OrderAction stopAction = isLong ? OrderAction.Sell : OrderAction.BuyToCover;
			OrderAction targetAction = stopAction;

			double slPrice = RoundToTick(slot.AverageEntryPrice + (isLong ? -1 : 1) * Parameters.SlTicks * TickSize);
			double tpPrice = RoundToTick(slot.AverageEntryPrice + (isLong ? 1 : -1) * Parameters.TpTicks * TickSize);

			string ocoId = "MAE-Bracket-" + Guid.NewGuid().ToString("N").Substring(0, 8);

			slot.StopLossOrder = slot.Account.CreateOrder(Instrument, stopAction, OrderType.StopMarket,
				OrderEntry.Manual, TimeInForce.Day, slot.Quantity, 0, slPrice, ocoId, "MAE-StopLoss", Core.Globals.MaxDate, null);

			slot.TargetOrder = slot.Account.CreateOrder(Instrument, targetAction, OrderType.Limit,
				OrderEntry.Manual, TimeInForce.Day, slot.Quantity, tpPrice, 0, ocoId, "MAE-Target", Core.Globals.MaxDate, null);

			slot.Account.Submit(new[] { slot.StopLossOrder, slot.TargetOrder });
		}

		private void OnExitFilled(AccountSlot slot, bool wasTarget, Execution exitExecution)
		{
			// NOTE: "Leave open after TP" in the source ad implies a *partial* close at TP that
			// leaves a runner behind. This first version brackets the full quantity at TP (a
			// complete close), so the flag has no effect yet -- wire up a PartialTpQuantity
			// parameter and split the target order if you want the runner behavior.
			bool wasLong = slot.Direction == MarketPosition.Long;
			double priceDiffTicks = (wasLong ? exitExecution.Price - slot.AverageEntryPrice : slot.AverageEntryPrice - exitExecution.Price) / TickSize;
			slot.LastTradeRealizedPnL = priceDiffTicks * TickSize * Instrument.MasterInstrument.PointValue * slot.Quantity;

			Log($"{AccountLabel(slot)}: {(wasTarget ? "TP" : "Stop loss")} alcanzado, P&L {slot.LastTradeRealizedPnL:0.00}");

			slot.ResetTradeState();

			if (slot.IsMaster)
				State = CycleState.Idle;

			Changed();
		}

		// ---------------------------------------------------------------
		// Replication
		// ---------------------------------------------------------------

		private void ReplicateToFollowers(AccountSlot master)
		{
			foreach (var replica in Slots.Where(s => !s.IsMaster && s.ReplicateEnabled && !s.DailyLimitHit))
			{
				int qty = Math.Max(1, (int)Math.Round(master.Quantity * replica.QuantityRatio));
				OrderAction action = master.Direction == MarketPosition.Long ? OrderAction.Buy : OrderAction.SellShort;

				var order = replica.Account.CreateOrder(Instrument, action, OrderType.Market, OrderEntry.Manual,
					TimeInForce.Day, qty, 0, 0, string.Empty, "MAE-ReplicaEntry", Core.Globals.MaxDate, null);

				replica.Account.Submit(new[] { order });
				Log($"Replicando a {AccountLabel(replica)}: {action} x{qty}");
			}
		}

		// ---------------------------------------------------------------
		// Break-even / trailing stop -- call on every market data price tick
		// ---------------------------------------------------------------

		public void OnPriceTick(double price)
		{
			foreach (var slot in Slots.Where(s => s.Direction != MarketPosition.Flat && s.StopLossOrder != null))
				UpdateProtectiveStop(slot, price);
		}

		private void UpdateProtectiveStop(AccountSlot slot, double price)
		{
			bool isLong = slot.Direction == MarketPosition.Long;
			double favorableTicks = (isLong ? price - slot.AverageEntryPrice : slot.AverageEntryPrice - price) / TickSize;

			double? newStop = null;

			if (Parameters.TrailingStopEnabled && favorableTicks >= Parameters.TrailingActivationTicks)
			{
				bool newExtreme = isLong ? price > slot.TrailingExtremePrice : price < slot.TrailingExtremePrice;
				if (newExtreme)
					slot.TrailingExtremePrice = price;

				newStop = slot.TrailingExtremePrice + (isLong ? -1 : 1) * Parameters.TrailingDistanceTicks * TickSize;
			}
			else if (Parameters.BreakEvenEnabled && !slot.BreakEvenApplied && favorableTicks >= Parameters.BreakEvenActivationTicks)
			{
				newStop = slot.AverageEntryPrice + (isLong ? 1 : -1) * Parameters.BreakEvenPlusTicks * TickSize;
			}

			if (newStop == null)
				return;

			double rounded = RoundToTick(newStop.Value);
			bool improves = isLong ? rounded > slot.StopLossOrder.StopPrice : rounded < slot.StopLossOrder.StopPrice;
			if (!improves)
				return;

			slot.StopLossOrder.StopPrice = rounded;
			slot.Account.Change(new[] { slot.StopLossOrder });
			slot.BreakEvenApplied = true;
		}

		// ---------------------------------------------------------------
		// Daily loss limit -- call roughly once a second
		// ---------------------------------------------------------------

		public void CheckDailyLossLimits()
		{
			foreach (var slot in Slots)
			{
				if (slot.DailyLimitHit)
					continue;

				double pnl = GetSessionPnL(slot);
				if (pnl <= -Math.Abs(Parameters.DailyLossLimit))
				{
					slot.DailyLimitHit = true;
					Log(AccountLabel(slot) + ": límite de pérdida diaria alcanzado, cerrando posición y cancelando órdenes.");
					FlattenSlot(slot);

					if (slot.IsMaster)
					{
						MasterSwitchOn = false;
						// Flattening the master doesn't go through OnExitFilled (the flatten order
						// isn't tracked as StopLossOrder/TargetOrder), so nothing else would ever
						// move the cycle back to Idle -- do it here or Launch stays blocked forever,
						// even after DailyLimitHit clears on the next session.
						State = CycleState.Idle;
					}

					Changed();
				}
			}
		}

		public double GetSessionPnL(AccountSlot slot)
		{
			double realized = slot.Account.Get(AccountItem.RealizedProfitLoss, Currency.UsDollar) - slot.SessionStartRealized;
			double unrealized = 0;

			var position = slot.Account.Positions.FirstOrDefault(p => p.Instrument == Instrument);
			if (position != null && position.MarketPosition != MarketPosition.Flat)
			{
				double last = Instrument.MarketData?.Last?.Price ?? position.AveragePrice;
				unrealized = position.GetUnrealizedProfitLoss(PerformanceUnit.Currency, last);
			}

			return realized + unrealized;
		}

		/// <summary>Resets each account's daily-loss baseline. Call once when the panel is applied
		/// and again whenever the calendar day rolls over (the window's timer handles the latter).</summary>
		public void MarkSessionStart()
		{
			foreach (var slot in Slots)
			{
				slot.SessionStartRealized = slot.Account.Get(AccountItem.RealizedProfitLoss, Currency.UsDollar);
				slot.DailyLimitHit = false;
			}
			lastEntryDate = Core.Globals.Now.Date;
		}

		// ---------------------------------------------------------------
		// Scheduled entry -- call roughly once a second
		// ---------------------------------------------------------------

		public void CheckScheduledEntry(DateTime now)
		{
			if (!Parameters.ScheduledEntryEnabled || !MasterSwitchOn || State != CycleState.Idle)
				return;

			if (now.Date != lastEntryDate && now.TimeOfDay >= Parameters.EntryTime
				&& now.TimeOfDay < Parameters.EntryTime.Add(TimeSpan.FromSeconds(5)))
			{
				LaunchDualEntry();
			}
		}

		// ---------------------------------------------------------------
		// Auto Volume Pro
		//
		// The source ad only promises "detects volume spikes ... executes automatically with
		// immediate protection" without specifying a directional rule. Rather than invent an
		// unproven direction signal, a spike here just re-arms the same dual-entry bracket used
		// by Launch/scheduled entry: it brackets both directions from the current price, and the
		// market itself decides which side fills, exactly like everywhere else in this tool.
		// Replace the LaunchDualEntry() call at the bottom of this method with your own
		// directional logic if you have one (e.g. bias by tick direction or order-flow delta).
		// ---------------------------------------------------------------

		public void OnVolumeTick(double cumulativeSessionVolume, DateTime time)
		{
			if (!Parameters.AutoVolumeProEnabled || !MasterSwitchOn)
				return;

			if (double.IsNaN(lastCumulativeVolume))
			{
				lastCumulativeVolume = cumulativeSessionVolume;
				bucketStart = time;
				return;
			}

			double delta = Math.Max(0, cumulativeSessionVolume - lastCumulativeVolume);
			lastCumulativeVolume = cumulativeSessionVolume;
			bucketVolume += delta;

			if ((time - bucketStart).TotalSeconds < 1)
				return;

			recentBucketVolumes.Enqueue(bucketVolume);
			while (recentBucketVolumes.Count > 30)
				recentBucketVolumes.Dequeue();

			double avg = recentBucketVolumes.Count > 0 ? recentBucketVolumes.Average() : 0;
			double justClosedBucket = bucketVolume;
			bucketVolume = 0;
			bucketStart = time;

			bool cooldownOver = (time - lastVolumeSignalTime).TotalSeconds >= Parameters.CooldownSeconds;

			if (avg > 0 && justClosedBucket >= avg * Parameters.VolumeMultiplier && cooldownOver && State == CycleState.Idle)
			{
				lastVolumeSignalTime = time;
				Log($"Auto Volume Pro: pico detectado ({justClosedBucket:0} vs promedio {avg:0}), disparando entrada.");
				LaunchDualEntry();
			}
		}

		// ---------------------------------------------------------------
		// Manual controls
		// ---------------------------------------------------------------

		public void CancelAllOrders()
		{
			foreach (var slot in Slots)
			{
				var working = new[] { slot.BuyStopEntry, slot.SellStopEntry, slot.StopLossOrder, slot.TargetOrder }
					.Where(o => o != null && IsCancelable(o)).ToArray();
				if (working.Length > 0)
					slot.Account.Cancel(working);
			}
			State = CycleState.Idle;
			Changed();
		}

		public void CloseAllPositions()
		{
			foreach (var slot in Slots)
				FlattenSlot(slot);
			// The flatten market order isn't tracked by OnExecutionUpdate, so there's no future
			// event that would otherwise clear the cycle state -- every order/position has already
			// been cancelled/reset synchronously above, so Idle is correct immediately.
			State = CycleState.Idle;
			Changed();
		}

		private void FlattenSlot(AccountSlot slot)
		{
			var working = new[] { slot.BuyStopEntry, slot.SellStopEntry, slot.StopLossOrder, slot.TargetOrder }
				.Where(o => o != null && IsCancelable(o)).ToArray();
			if (working.Length > 0)
				slot.Account.Cancel(working);

			var position = slot.Account.Positions.FirstOrDefault(p => p.Instrument == Instrument);
			if (position != null && position.MarketPosition != MarketPosition.Flat)
			{
				OrderAction action = position.MarketPosition == MarketPosition.Long ? OrderAction.Sell : OrderAction.BuyToCover;
				var flatten = slot.Account.CreateOrder(Instrument, action, OrderType.Market, OrderEntry.Manual,
					TimeInForce.Day, Math.Abs(position.Quantity), 0, 0, string.Empty, "MAE-Flatten", Core.Globals.MaxDate, null);
				slot.Account.Submit(new[] { flatten });
			}

			slot.ResetTradeState();
		}

		private double RoundToTick(double price)
		{
			return Instrument.MasterInstrument.RoundToTickSize(price);
		}

		private string AccountLabel(AccountSlot slot)
		{
			return (slot.IsMaster ? "[Master] " : "[Replica] ") + slot.Account.DisplayName;
		}
	}
}
