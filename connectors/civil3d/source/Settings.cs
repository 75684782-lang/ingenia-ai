using System;
using System.IO;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Xml.Linq;

namespace Ingenia.Bridge
{
    internal sealed class BridgeSettings
    {
        public string Host { get; set; } = "127.0.0.1";
        public int Port { get; set; } = 8756;
        public string Token { get; set; } = "";
        public int RequestTimeoutSeconds { get; set; } = 60;
        public string LogLevel { get; set; } = "info";

        public static BridgeSettings Load()
        {
            var settings = new BridgeSettings();

            var file = Path.Combine(
                Path.GetDirectoryName(typeof(BridgeSettings).Assembly.Location) ?? AppContext.BaseDirectory,
                "ingenia.bridge.json");

            if (File.Exists(file))
            {
                try
                {
                    var json = File.ReadAllText(file);
                    var fromFile = JsonSerializer.Deserialize<BridgeSettings>(
                        json,
                        new JsonSerializerOptions { PropertyNameCaseInsensitive = true });
                    if (fromFile != null)
                    {
                        settings = fromFile;
                    }
                }
                catch (Exception ex)
                {
                    Log.Warn($"No se pudo leer {file}: {ex.Message}");
                }
            }

            settings.Host = Environment.GetEnvironmentVariable("INGENIA_BRIDGE_HOST") ?? settings.Host;
            settings.Token = Environment.GetEnvironmentVariable("INGENIA_CIVIL3D_TOKEN") ?? settings.Token;

            var portText = Environment.GetEnvironmentVariable("INGENIA_BRIDGE_PORT");
            if (int.TryParse(portText, out var port))
            {
                settings.Port = port;
            }

            var timeoutText = Environment.GetEnvironmentVariable("INGENIA_BRIDGE_TIMEOUT");
            if (int.TryParse(timeoutText, out var timeout) && timeout > 0)
            {
                settings.RequestTimeoutSeconds = timeout;
            }

            if (string.IsNullOrWhiteSpace(settings.Token))
            {
                Log.Warn(
                    "No hay token configurado. El puente rechazara TODAS las solicitudes. " +
                    "Define INGENIA_CIVIL3D_TOKEN o crea ingenia.bridge.json junto al plugin.");
            }

            return settings;
        }
    }
}
