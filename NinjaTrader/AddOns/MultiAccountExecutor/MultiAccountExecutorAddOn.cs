#region Using declarations
using System;
using System.Linq;
using System.Windows;
using NinjaTrader.Gui;
using NinjaTrader.Gui.Tools;
#endregion

namespace NinjaTrader.NinjaScript.AddOns.MultiAccountExecutor
{
	/// <summary>
	/// Registers a "Multi-Account Executor" item under the Control Center's New menu. The exact
	/// internal name of that menu ("MenuItemNew") matches NinjaTrader's own published AddOn
	/// sample; if it doesn't appear after compiling, your NT8 build renamed that control -- see
	/// the README for how to open the window directly as a fallback while that gets sorted out.
	/// </summary>
	public class MultiAccountExecutorAddOn : AddOnBase
	{
		private NTMenuItem menuItem;
		private MultiAccountExecutorWindow window;

		protected override void OnStateChange()
		{
			if (State == State.SetDefaults)
				Name = "Multi-Account Executor";
		}

		protected override void OnWindowCreated(Window ntWindow)
		{
			var controlCenter = ntWindow as NTWindow;
			if (controlCenter == null || controlCenter.Caption == null || !controlCenter.Caption.Contains("Control Center"))
				return;

			var newMenuItem = controlCenter.MainMenu?.Items
				.OfType<NTMenuItem>()
				.FirstOrDefault(m => m.Name == "MenuItemNew");

			if (newMenuItem == null)
				return;

			menuItem = new NTMenuItem { Header = "Multi-Account Executor" };
			menuItem.Click += (s, e) => OpenWindow();
			newMenuItem.Items.Add(menuItem);
		}

		protected override void OnWindowDestroyed(Window ntWindow)
		{
			var controlCenter = ntWindow as NTWindow;
			if (controlCenter == null || menuItem == null)
				return;

			var newMenuItem = controlCenter.MainMenu?.Items
				.OfType<NTMenuItem>()
				.FirstOrDefault(m => m.Name == "MenuItemNew");
			newMenuItem?.Items.Remove(menuItem);
			menuItem = null;
		}

		private void OpenWindow()
		{
			if (window == null || !window.IsLoaded)
				window = new MultiAccountExecutorWindow();

			window.Show();
			window.Activate();
		}
	}
}
