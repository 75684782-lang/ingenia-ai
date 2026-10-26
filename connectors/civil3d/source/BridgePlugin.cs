using System;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.Runtime;
using AcApp = Autodesk.AutoCAD.ApplicationServices.Application;
using AcDoc = Autodesk.AutoCAD.ApplicationServices.Document;

namespace Ingenia.Bridge
{
    /// <summary>
    /// Entry point loaded by AutoCAD / Civil 3D (NETLOAD or Autoloader).
    /// It starts a loopback-only bridge that the local Ingenia AI backend calls.
    /// </summary>
    public sealed class BridgePlugin : IExtensionApplication
    {
        private static HttpBridge? _bridge;
        private static BridgeSettings? _settings;
        private static readonly object Sync = new object();

        public void Initialize()
        {
            try
            {
                Log.Info("IngeniaBridge inicializando.");
                MainThreadDispatcher.Start();
                StartBridge();
            }
            catch (Exception ex)
            {
                Log.Error("No se pudo inicializar IngeniaBridge", ex);
            }
        }

        public void Terminate()
        {
            StopBridge();
            MainThreadDispatcher.Stop();
            Log.Info("IngeniaBridge detenido.");
        }

        internal static void StartBridge()
        {
            lock (Sync)
            {
                if (_bridge != null)
                {
                    return;
                }
                _settings ??= BridgeSettings.Load();
                _bridge = new HttpBridge(_settings);
                _bridge.Start();
            }
        }

        internal static void StopBridge()
        {
            lock (Sync)
            {
                _bridge?.Dispose();
                _bridge = null;
            }
        }

        internal static string StatusText()
        {
            if (_settings == null)
            {
                return "IngeniaBridge: sin configuracion cargada.";
            }
            var running = _bridge != null;
            var token = string.IsNullOrWhiteSpace(_settings.Token) ? "SIN TOKEN (rechaza todo)" : "configurado";
            return
                $"IngeniaBridge {(running ? "activo" : "detenido")} en http://{_settings.Host}:{_settings.Port}/ · token: {token}";
        }
    }

    public static class BridgeCommands
    {
        [CommandMethod("INGENIABRIDGE", CommandFlags.Modal)]
        public static void ShowStatus()
        {
            Write(BridgePlugin.StatusText());
        }

        [CommandMethod("INGENIABRIDGE_START", CommandFlags.Modal)]
        public static void Start()
        {
            BridgePlugin.StartBridge();
            Write("Puente iniciado. " + BridgePlugin.StatusText());
        }

        [CommandMethod("INGENIABRIDGE_STOP", CommandFlags.Modal)]
        public static void Stop()
        {
            BridgePlugin.StopBridge();
            Write("Puente detenido.");
        }

        private static void Write(string message)
        {
            AcDoc? doc = AcApp.DocumentManager.MdiActiveDocument;
            doc?.Editor.WriteMessage($"\n[Ingenia] {message}\n");
            Log.Info(message);
        }
    }
}
