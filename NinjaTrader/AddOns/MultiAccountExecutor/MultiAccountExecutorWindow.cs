#region Using declarations
using System;
using System.Collections.Generic;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Media;
using System.Windows.Threading;
using NinjaTrader.Cbi;
using NinjaTrader.Gui;
#endregion

namespace NinjaTrader.NinjaScript.AddOns.MultiAccountExecutor
{
	/// <summary>
	/// Floating control panel: configures the master account/instrument, dual-entry and
	/// risk-management parameters, the list of replica accounts, and shows live P&amp;L/position
	/// status. All order routing lives in <see cref="MultiAccountExecutorEngine"/> -- this class
	/// only reads/writes controls and drives the engine's periodic checks off a DispatcherTimer.
	/// </summary>
	public class MultiAccountExecutorWindow : NTWindow
	{
		private readonly MultiAccountExecutorEngine engine = new MultiAccountExecutorEngine();
		private readonly DispatcherTimer timer = new DispatcherTimer { Interval = TimeSpan.FromSeconds(1) };
		private DateTime lastCheckedDate = DateTime.MinValue;

		// Cuenta / instrumento / estado
		private ComboBox masterAccountCombo;
		private TextBox instrumentTextBox;
		private ToggleButton estadoToggle;
		private ToggleButton masterSwitchToggle;

		// Entrada dual
		private TextBox entryContractsBox, offsetBox, tpBox, slBox, dailyLossBox, entryTimeBox;
		private CheckBox leaveOpenAfterTpBox, scheduledEntryBox;

		// Break even
		private ToggleButton breakEvenToggle;
		private TextBox beActivationBox, bePlusBox;

		// Trailing stop
		private ToggleButton trailingToggle;
		private TextBox trailDistanceBox, trailActivationBox;

		// Auto volume pro
		private ToggleButton volumeProToggle;
		private TextBox volumeMultiplierBox, cooldownBox;

		// Réplica de cuentas
		private StackPanel replicaListPanel;
		private readonly Dictionary<Account, (CheckBox enabled, TextBox ratio)> replicaControls = new Dictionary<Account, (CheckBox, TextBox)>();

		// Monitoreo / info
		private TextBlock pnlActualText, pnlLastText, posOpenText, contractsText, durationText;
		private TextBlock directionText, entryPriceText, currentPriceText, unrealizedText, realizedText;
		private TextBox logBox;
		private DateTime tradeStartTime;
		private bool wasFlat = true;

		public MultiAccountExecutorWindow()
		{
			Caption = "Multi-Account Executor";
			Width = 760;
			Height = 640;

			engine.Log += line => Dispatcher.InvokeAsync(() => AppendLog(line));
			engine.Changed += () => Dispatcher.InvokeAsync(RefreshMonitoring);

			BuildUi();
			PopulateAccountCombos();

			timer.Tick += (s, e) => OnTimerTick();
			timer.Start();

			Closed += (s, e) =>
			{
				timer.Stop();
				engine.DetachAll();
			};
		}

		// ---------------------------------------------------------------
		// UI construction
		// ---------------------------------------------------------------

		private void BuildUi()
		{
			var root = new ScrollViewer { VerticalScrollBarVisibility = ScrollBarVisibility.Auto };
			var stack = new StackPanel { Margin = new Thickness(10) };
			root.Content = stack;
			Content = root;

			stack.Children.Add(BuildAccountSection());
			stack.Children.Add(BuildDualEntrySection());
			stack.Children.Add(BuildRiskManagementSection());
			stack.Children.Add(BuildReplicaSection());
			stack.Children.Add(BuildMonitoringSection());
			stack.Children.Add(BuildButtonBar());
			stack.Children.Add(BuildLogSection());
		}

		private GroupBox Section(string header, UIElement content)
		{
			return new GroupBox { Header = header, Margin = new Thickness(0, 0, 0, 8), Content = content };
		}

		private static TextBox LabeledField(Panel parent, string label, string defaultValue, double width = 70)
		{
			var row = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(0, 2, 0, 2) };
			row.Children.Add(new TextBlock { Text = label, Width = 200, VerticalAlignment = VerticalAlignment.Center });
			var box = new TextBox { Text = defaultValue, Width = width };
			row.Children.Add(box);
			parent.Children.Add(row);
			return box;
		}

		private UIElement BuildAccountSection()
		{
			var grid = new StackPanel();

			var accRow = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(0, 2, 0, 2) };
			accRow.Children.Add(new TextBlock { Text = "Cuenta maestra", Width = 200, VerticalAlignment = VerticalAlignment.Center });
			masterAccountCombo = new ComboBox { Width = 160 };
			masterAccountCombo.SelectionChanged += (s, e) => RebuildReplicaList();
			accRow.Children.Add(masterAccountCombo);
			grid.Children.Add(accRow);

			var instRow = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(0, 2, 0, 2) };
			instRow.Children.Add(new TextBlock { Text = "Instrumento (ej. NQ SEP25)", Width = 200, VerticalAlignment = VerticalAlignment.Center });
			instrumentTextBox = new TextBox { Text = "NQ SEP25", Width = 160 };
			instRow.Children.Add(instrumentTextBox);
			grid.Children.Add(instRow);

			var stateRow = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(0, 6, 0, 2) };
			estadoToggle = new ToggleButton { Content = "ESTADO: OFF", Width = 150 };
			estadoToggle.Click += (s, e) => estadoToggle.Content = estadoToggle.IsChecked == true ? "ESTADO: ON" : "ESTADO: OFF";
			masterSwitchToggle = new ToggleButton { Content = "MASTER SWITCH: OFF", Width = 180, Margin = new Thickness(10, 0, 0, 0) };
			masterSwitchToggle.Click += (s, e) =>
			{
				engine.MasterSwitchOn = masterSwitchToggle.IsChecked == true;
				masterSwitchToggle.Content = engine.MasterSwitchOn ? "MASTER SWITCH: ON" : "MASTER SWITCH: OFF";
			};
			stateRow.Children.Add(estadoToggle);
			stateRow.Children.Add(masterSwitchToggle);
			grid.Children.Add(stateRow);

			return Section("Cuenta / Instrumento / Estado", grid);
		}

		private UIElement BuildDualEntrySection()
		{
			var grid = new StackPanel();
			entryContractsBox = LabeledField(grid, "Entry contracts", "1");
			offsetBox = LabeledField(grid, "Offset (ticks)", "10");
			tpBox = LabeledField(grid, "TP limit (ticks)", "60");
			slBox = LabeledField(grid, "Stop loss (ticks)", "40");

			var leaveRow = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(0, 2, 0, 2) };
			leaveOpenAfterTpBox = new CheckBox { Content = "Leave open after TP (requiere tamaño parcial, ver README)", IsChecked = true };
			leaveRow.Children.Add(leaveOpenAfterTpBox);
			grid.Children.Add(leaveRow);

			dailyLossBox = LabeledField(grid, "Daily loss limit ($) por cuenta", "1000");

			var schedRow = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(0, 2, 0, 2) };
			scheduledEntryBox = new CheckBox { Content = "Entrada programada", VerticalAlignment = VerticalAlignment.Center, Width = 200 };
			entryTimeBox = new TextBox { Text = "09:29:58", Width = 70 };
			schedRow.Children.Add(scheduledEntryBox);
			schedRow.Children.Add(entryTimeBox);
			grid.Children.Add(schedRow);

			return Section("Configuración Entrada Dual (cuenta maestra)", grid);
		}

		private UIElement BuildRiskManagementSection()
		{
			var wrap = new WrapPanel();

			var beGrid = new StackPanel { Width = 350, Margin = new Thickness(0, 0, 10, 0) };
			breakEvenToggle = new ToggleButton { Content = "BREAK EVEN: OFF", Width = 150, Margin = new Thickness(0, 0, 0, 4) };
			breakEvenToggle.Click += (s, e) => breakEvenToggle.Content = breakEvenToggle.IsChecked == true ? "BREAK EVEN: ON" : "BREAK EVEN: OFF";
			beGrid.Children.Add(breakEvenToggle);
			beActivationBox = LabeledField(beGrid, "Breakeven activation (ticks)", "10");
			bePlusBox = LabeledField(beGrid, "Breakeven plus (ticks)", "5");

			var trailGrid = new StackPanel { Width = 350 };
			trailingToggle = new ToggleButton { Content = "TRAILING STOP: OFF", Width = 150, Margin = new Thickness(0, 0, 0, 4) };
			trailingToggle.Click += (s, e) => trailingToggle.Content = trailingToggle.IsChecked == true ? "TRAILING STOP: ON" : "TRAILING STOP: OFF";
			trailGrid.Children.Add(trailingToggle);
			trailDistanceBox = LabeledField(trailGrid, "Trailing distance (ticks)", "20");
			trailActivationBox = LabeledField(trailGrid, "Trailing activation (ticks)", "20");

			wrap.Children.Add(beGrid);
			wrap.Children.Add(trailGrid);

			var volGrid = new StackPanel { Margin = new Thickness(0, 8, 0, 0) };
			volumeProToggle = new ToggleButton { Content = "AUTO VOLUME PRO: OFF", Width = 180, Margin = new Thickness(0, 0, 0, 4) };
			volumeProToggle.Click += (s, e) => volumeProToggle.Content = volumeProToggle.IsChecked == true ? "AUTO VOLUME PRO: ON" : "AUTO VOLUME PRO: OFF";
			volGrid.Children.Add(volumeProToggle);
			volumeMultiplierBox = LabeledField(volGrid, "Volume multiplier", "1.5");
			cooldownBox = LabeledField(volGrid, "Cooldown (segundos)", "30");

			var outer = new StackPanel();
			outer.Children.Add(wrap);
			outer.Children.Add(volGrid);

			return Section("Break Even / Trailing Stop / Auto Volume Pro", outer);
		}

		private UIElement BuildReplicaSection()
		{
			replicaListPanel = new StackPanel();
			var wrapper = new StackPanel();
			wrapper.Children.Add(new TextBlock
			{
				Text = "Cuentas que replican la operación de la cuenta maestra. Ratio = multiplicador de contratos (1.0 = misma cantidad).",
				TextWrapping = TextWrapping.Wrap,
				Margin = new Thickness(0, 0, 0, 6)
			});
			wrapper.Children.Add(replicaListPanel);
			return Section("Replicador de Cuentas", wrapper);
		}

		private UIElement BuildMonitoringSection()
		{
			var wrap = new WrapPanel();

			var monGrid = new StackPanel { Width = 350, Margin = new Thickness(0, 0, 10, 0) };
			pnlActualText = AddInfoRow(monGrid, "P&L actual ($)");
			pnlLastText = AddInfoRow(monGrid, "P&L última operación ($)");
			posOpenText = AddInfoRow(monGrid, "Posición abierta");
			contractsText = AddInfoRow(monGrid, "Contratos abiertos");
			durationText = AddInfoRow(monGrid, "Duración");

			var infoGrid = new StackPanel { Width = 350 };
			directionText = AddInfoRow(infoGrid, "Dirección");
			entryPriceText = AddInfoRow(infoGrid, "Precio entrada");
			currentPriceText = AddInfoRow(infoGrid, "Precio actual");
			unrealizedText = AddInfoRow(infoGrid, "Unrealized PNL ($)");
			realizedText = AddInfoRow(infoGrid, "Realized PNL ($)");

			wrap.Children.Add(monGrid);
			wrap.Children.Add(infoGrid);

			return Section("Monitoreo (cuenta maestra)", wrap);
		}

		private TextBlock AddInfoRow(Panel parent, string label)
		{
			var row = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(0, 2, 0, 2) };
			row.Children.Add(new TextBlock { Text = label, Width = 220, VerticalAlignment = VerticalAlignment.Center });
			var value = new TextBlock { Text = "--", FontWeight = FontWeights.Bold };
			row.Children.Add(value);
			parent.Children.Add(row);
			return value;
		}

		private UIElement BuildButtonBar()
		{
			var row = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(0, 4, 0, 8) };

			var closeBtn = new Button { Content = "CLOSE POSITION", Width = 140, Margin = new Thickness(0, 0, 6, 0), Background = Brushes.IndianRed };
			closeBtn.Click += (s, e) => engine.CloseAllPositions();

			var cancelBtn = new Button { Content = "CANCEL ORDERS", Width = 140, Margin = new Thickness(0, 0, 6, 0) };
			cancelBtn.Click += (s, e) => engine.CancelAllOrders();

			var applyBtn = new Button { Content = "APPLY", Width = 100, Margin = new Thickness(0, 0, 6, 0) };
			applyBtn.Click += (s, e) => ApplyToEngine();

			var launchBtn = new Button { Content = "LAUNCH", Width = 100, Background = Brushes.OliveDrab };
			launchBtn.Click += (s, e) => OnLaunchClicked();

			row.Children.Add(closeBtn);
			row.Children.Add(cancelBtn);
			row.Children.Add(applyBtn);
			row.Children.Add(launchBtn);
			return row;
		}

		private UIElement BuildLogSection()
		{
			logBox = new TextBox
			{
				Height = 120,
				IsReadOnly = true,
				TextWrapping = TextWrapping.Wrap,
				VerticalScrollBarVisibility = ScrollBarVisibility.Auto
			};
			return Section("Registro", logBox);
		}

		// ---------------------------------------------------------------
		// Account plumbing
		// ---------------------------------------------------------------

		private void PopulateAccountCombos()
		{
			masterAccountCombo.ItemsSource = Account.All.ToList();
			masterAccountCombo.DisplayMemberPath = "DisplayName";
			if (masterAccountCombo.Items.Count > 0)
				masterAccountCombo.SelectedIndex = 0;
		}

		private void RebuildReplicaList()
		{
			replicaListPanel.Children.Clear();
			replicaControls.Clear();

			var master = masterAccountCombo.SelectedItem as Account;
			foreach (var account in Account.All.Where(a => a != master))
			{
				var row = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(0, 2, 0, 2) };
				var chk = new CheckBox { Content = account.DisplayName, Width = 220, VerticalAlignment = VerticalAlignment.Center };
				var ratio = new TextBox { Text = "1.0", Width = 60 };
				row.Children.Add(chk);
				row.Children.Add(new TextBlock { Text = "ratio", Margin = new Thickness(6, 0, 4, 0), VerticalAlignment = VerticalAlignment.Center });
				row.Children.Add(ratio);
				replicaListPanel.Children.Add(row);
				replicaControls[account] = (chk, ratio);
			}
		}

		// ---------------------------------------------------------------
		// Apply / Launch
		// ---------------------------------------------------------------

		private void ApplyToEngine()
		{
			var master = masterAccountCombo.SelectedItem as Account;
			if (master == null)
			{
				AppendLog("Seleccioná una cuenta maestra.");
				return;
			}

			Instrument instrument;
			try
			{
				instrument = Instrument.GetInstrument(instrumentTextBox.Text);
			}
			catch (Exception ex)
			{
				AppendLog("No se pudo resolver el instrumento: " + ex.Message);
				return;
			}

			if (instrument == null)
			{
				AppendLog("Instrumento no encontrado: " + instrumentTextBox.Text);
				return;
			}

			engine.DetachAll();
			engine.Instrument = instrument;
			engine.AttachAccount(master, isMaster: true);

			foreach (var kvp in replicaControls)
			{
				if (kvp.Value.enabled.IsChecked != true)
					continue;

				engine.AttachAccount(kvp.Key, isMaster: false);
				var slot = engine.Slots.First(s => s.Account == kvp.Key);
				slot.QuantityRatio = ParseDouble(kvp.Value.ratio.Text, 1.0);
			}

			engine.Parameters = new ExecutionParameters
			{
				EntryContracts = ParseInt(entryContractsBox.Text, 1),
				OffsetTicks = ParseInt(offsetBox.Text, 10),
				TpTicks = ParseInt(tpBox.Text, 60),
				SlTicks = ParseInt(slBox.Text, 40),
				LeaveOpenAfterTp = leaveOpenAfterTpBox.IsChecked == true,
				DailyLossLimit = ParseDouble(dailyLossBox.Text, 1000),
				ScheduledEntryEnabled = scheduledEntryBox.IsChecked == true,
				EntryTime = TimeSpan.TryParse(entryTimeBox.Text, out var t) ? t : new TimeSpan(9, 29, 58),
				BreakEvenEnabled = breakEvenToggle.IsChecked == true,
				BreakEvenActivationTicks = ParseInt(beActivationBox.Text, 10),
				BreakEvenPlusTicks = ParseInt(bePlusBox.Text, 5),
				TrailingStopEnabled = trailingToggle.IsChecked == true,
				TrailingDistanceTicks = ParseInt(trailDistanceBox.Text, 20),
				TrailingActivationTicks = ParseInt(trailActivationBox.Text, 20),
				AutoVolumeProEnabled = volumeProToggle.IsChecked == true,
				VolumeMultiplier = ParseDouble(volumeMultiplierBox.Text, 1.5),
				CooldownSeconds = ParseInt(cooldownBox.Text, 30)
			};

			engine.MasterSwitchOn = masterSwitchToggle.IsChecked == true;
			engine.MarkSessionStart();
			lastCheckedDate = Core.Globals.Now.Date;

			instrument.MarketData.Update -= OnMarketDataUpdate;
			instrument.MarketData.Update += OnMarketDataUpdate;

			AppendLog($"Configuración aplicada. Maestra: {master.DisplayName} · Réplicas activas: {engine.Slots.Count(s => !s.IsMaster)} · Instrumento: {instrument.FullName}");
		}

		private void OnLaunchClicked()
		{
			if (estadoToggle.IsChecked != true)
			{
				AppendLog("ESTADO está en OFF; activalo antes de lanzar.");
				return;
			}
			if (engine.Instrument == null || engine.Master == null)
			{
				AppendLog("Aplicá la configuración (APPLY) antes de lanzar.");
				return;
			}
			engine.LaunchDualEntry();
		}

		private void OnMarketDataUpdate(object sender, NinjaTrader.Data.MarketDataEventArgs e)
		{
			if (e.MarketDataType != NinjaTrader.Data.MarketDataType.Last)
				return;

			engine.OnPriceTick(e.Price);
			engine.OnVolumeTick(e.Volume, e.Time);
		}

		// ---------------------------------------------------------------
		// Periodic refresh
		// ---------------------------------------------------------------

		private void OnTimerTick()
		{
			var now = Core.Globals.Now;
			if (now.Date != lastCheckedDate)
			{
				lastCheckedDate = now.Date;
				engine.MarkSessionStart();
			}

			if (engine.Master != null)
			{
				engine.CheckDailyLossLimits();
				engine.CheckScheduledEntry(now);
			}

			RefreshMonitoring();
		}

		private void RefreshMonitoring()
		{
			var master = engine.Master;
			if (master == null || engine.Instrument == null)
				return;

			double currentPrice = engine.Instrument.MarketData?.Last?.Price ?? 0;
			double pnl = engine.GetSessionPnL(master);

			// Mark the moment the master goes from flat to in-position exactly once, on the
			// transition, instead of re-stamping it on every 1s poll while flat.
			if (wasFlat && !master.IsFlat)
				tradeStartTime = Core.Globals.Now;
			wasFlat = master.IsFlat;

			double sessionRealized = master.Account.Get(AccountItem.RealizedProfitLoss, Currency.UsDollar) - master.SessionStartRealized;

			pnlActualText.Text = pnl.ToString("0.00");
			pnlLastText.Text = master.LastTradeRealizedPnL.ToString("0.00");
			posOpenText.Text = master.IsFlat ? "0" : "1";
			contractsText.Text = master.Quantity.ToString();
			durationText.Text = master.IsFlat ? "00:00:00" : (Core.Globals.Now - tradeStartTime).ToString(@"hh\:mm\:ss");
			realizedText.Text = sessionRealized.ToString("0.00");

			directionText.Text = master.Direction.ToString().ToUpperInvariant();
			entryPriceText.Text = master.IsFlat ? "--" : master.AverageEntryPrice.ToString("0.00");
			currentPriceText.Text = currentPrice.ToString("0.00");

			if (!master.IsFlat)
			{
				double unrealizedTicks = master.Direction == MarketPosition.Long ? currentPrice - master.AverageEntryPrice : master.AverageEntryPrice - currentPrice;
				double perContractPointValue = engine.Instrument.MasterInstrument.PointValue;
				double unrealizedDollars = unrealizedTicks * perContractPointValue * master.Quantity;
				unrealizedText.Text = unrealizedDollars.ToString("0.00");
			}
			else
			{
				unrealizedText.Text = "0.00";
			}
		}

		private void AppendLog(string line)
		{
			logBox.AppendText($"[{Core.Globals.Now:HH:mm:ss}] {line}\n");
			logBox.ScrollToEnd();
		}

		private static int ParseInt(string text, int fallback) => int.TryParse(text, out var v) ? v : fallback;
		private static double ParseDouble(string text, double fallback) => double.TryParse(text, out var v) ? v : fallback;
	}
}
