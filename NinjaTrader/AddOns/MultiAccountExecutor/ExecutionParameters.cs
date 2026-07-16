using System;

namespace NinjaTrader.NinjaScript.AddOns.MultiAccountExecutor
{
	/// <summary>Snapshot of every configurable input from the panel, captured on "Apply".</summary>
	public class ExecutionParameters
	{
		public int EntryContracts = 1;
		public int OffsetTicks = 10;
		public int TpTicks = 60;
		public int SlTicks = 40;
		public bool LeaveOpenAfterTp = true;
		public double DailyLossLimit = 1000;

		public bool ScheduledEntryEnabled;
		public TimeSpan EntryTime = new TimeSpan(9, 29, 58);

		public bool BreakEvenEnabled = true;
		public int BreakEvenActivationTicks = 10;
		public int BreakEvenPlusTicks = 5;

		public bool TrailingStopEnabled = true;
		public int TrailingDistanceTicks = 20;
		public int TrailingActivationTicks = 20;

		public bool AutoVolumeProEnabled;
		public double VolumeMultiplier = 1.5;
		public int CooldownSeconds = 30;

		public ExecutionParameters Clone()
		{
			return (ExecutionParameters)MemberwiseClone();
		}
	}
}
