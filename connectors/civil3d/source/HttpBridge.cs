using System;
using System.Collections.Generic;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;

namespace Ingenia.Bridge
{
    /// <summary>
    /// Minimal HTTP/1.1 server bound to 127.0.0.1 only.
    /// A raw TcpListener is used instead of HttpListener so the plugin does not
    /// require URL ACL reservations or administrator rights.
    /// </summary>
    internal sealed class HttpBridge : IDisposable
    {
        private const int MaxHeaderBytes = 64 * 1024;
        private const int MaxBodyBytes = 4 * 1024 * 1024;

        private readonly BridgeSettings _settings;
        private readonly JsonSerializerOptions _json = new JsonSerializerOptions
        {
            PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
            WriteIndented = false,
            DefaultIgnoreCondition = System.Text.Json.Serialization.JsonIgnoreCondition.WhenWritingNull,
        };

        private TcpListener? _listener;
        private CancellationTokenSource? _cts;
        private Task? _loop;

        public HttpBridge(BridgeSettings settings)
        {
            _settings = settings;
        }

        public void Start()
        {
            if (_listener != null)
            {
                return;
            }

            var address = IPAddress.Parse(_settings.Host);
            _listener = new TcpListener(address, _settings.Port);
            _listener.Start();
            _cts = new CancellationTokenSource();
            _loop = Task.Run(() => LoopAsync(_cts.Token));
            Log.Info($"Puente escuchando en http://{_settings.Host}:{_settings.Port}/");
        }

        public void Stop()
        {
            try
            {
                _cts?.Cancel();
                _listener?.Stop();
            }
            catch (Exception ex)
            {
                Log.Warn($"Error deteniendo el puente: {ex.Message}");
            }
            finally
            {
                _listener = null;
                _cts?.Dispose();
                _cts = null;
            }
        }

        public void Dispose() => Stop();

        private async Task LoopAsync(CancellationToken token)
        {
            while (!token.IsCancellationRequested && _listener != null)
            {
                TcpClient client;
                try
                {
                    client = await _listener.AcceptTcpClientAsync().ConfigureAwait(false);
                }
                catch (Exception) when (token.IsCancellationRequested)
                {
                    return;
                }
                catch (ObjectDisposedException)
                {
                    return;
                }
                catch (Exception ex)
                {
                    Log.Warn($"Accept: {ex.Message}");
                    continue;
                }

                _ = Task.Run(() => HandleClientAsync(client), token);
            }
        }

        private async Task HandleClientAsync(TcpClient client)
        {
            using (client)
            {
                client.NoDelay = true;
                using var stream = client.GetStream();
                try
                {
                    var request = await ReadRequestAsync(stream).ConfigureAwait(false);
                    if (request == null)
                    {
                        await WriteAsync(stream, 400, ErrorJson("Solicitud HTTP invalida.")).ConfigureAwait(false);
                        return;
                    }

                    if (!IsAuthorized(request.Headers))
                    {
                        await WriteAsync(stream, 401, ErrorJson("Token local invalido.")).ConfigureAwait(false);
                        return;
                    }

                    if (string.Equals(request.Path, "/status", StringComparison.OrdinalIgnoreCase))
                    {
                        if (!string.Equals(request.Method, "GET", StringComparison.OrdinalIgnoreCase))
                        {
                            await WriteAsync(stream, 405, ErrorJson("Metodo no permitido.")).ConfigureAwait(false);
                            return;
                        }
                        var status = await MainThreadDispatcher
                            .Enqueue((doc, tr) => ToolHandlers.Dispatch("get_civil3d_status", default, doc, tr))
                            .ConfigureAwait(false);
                        if (status.Ok)
                        {
                            await WriteAsync(stream, 200, JsonSerializer.Serialize(new
                            {
                                connected = true,
                                mode = "real",
                                plugin = "IngeniaBridge",
                                data = status.Data,
                                serverTime = DateTime.UtcNow.ToString("o"),
                            }, _json)).ConfigureAwait(false);
                        }
                        else
                        {
                            await WriteAsync(stream, 200, JsonSerializer.Serialize(new
                            {
                                connected = false,
                                mode = "real",
                                error = status.Error,
                            }, _json)).ConfigureAwait(false);
                        }
                        return;
                    }

                    if (!string.Equals(request.Path, "/rpc", StringComparison.OrdinalIgnoreCase))
                    {
                        await WriteAsync(stream, 404, ErrorJson("Ruta no encontrada.")).ConfigureAwait(false);
                        return;
                    }

                    if (!string.Equals(request.Method, "POST", StringComparison.OrdinalIgnoreCase))
                    {
                        await WriteAsync(stream, 405, ErrorJson("Metodo no permitido.")).ConfigureAwait(false);
                        return;
                    }

                    BridgeRequest? payload;
                    try
                    {
                        payload = JsonSerializer.Deserialize<BridgeRequest>(request.Body, _json);
                    }
                    catch (Exception ex)
                    {
                        await WriteAsync(stream, 400, ErrorJson($"JSON invalido: {ex.Message}")).ConfigureAwait(false);
                        return;
                    }

                    if (payload == null || string.IsNullOrWhiteSpace(payload.Tool))
                    {
                        await WriteAsync(stream, 400, ErrorJson("Falta el campo tool.")).ConfigureAwait(false);
                        return;
                    }

                    if (!ToolHandlers.IsKnown(payload.Tool))
                    {
                        await WriteAsync(
                            stream,
                            200,
                            JsonSerializer.Serialize(
                                BridgeResponse.Failure("Herramienta no permitida por el puente.", payload.Tool, payload.RequestId),
                                _json)).ConfigureAwait(false);
                        return;
                    }

                    Log.Info($"Solicitud {payload.RequestId} -> {payload.Tool}");
                    var task = MainThreadDispatcher.Enqueue(
                        (doc, tr) => ToolHandlers.Dispatch(payload.Tool, payload.Args, doc, tr));

                    var timeout = Task.Delay(TimeSpan.FromSeconds(_settings.RequestTimeoutSeconds));
                    if (await Task.WhenAny(task, timeout).ConfigureAwait(false) != task)
                    {
                        await WriteAsync(
                            stream,
                            200,
                            JsonSerializer.Serialize(
                                BridgeResponse.Failure(
                                    "La operacion excedio el tiempo de espera; su estado es incierto.",
                                    payload.Tool,
                                    payload.RequestId),
                                _json)).ConfigureAwait(false);
                        return;
                    }

                    var result = await task.ConfigureAwait(false);
                    var response = result.Ok
                        ? new BridgeResponse
                        {
                            Ok = true,
                            Tool = payload.Tool,
                            RequestId = payload.RequestId,
                            Data = result.Data,
                        }
                        : BridgeResponse.Failure(
                            result.Error ?? "Error desconocido.", payload.Tool, payload.RequestId);

                    await WriteAsync(
                        stream, 200, JsonSerializer.Serialize(response, _json)).ConfigureAwait(false);
                }
                catch (Exception ex)
                {
                    Log.Error("Error atendiendo solicitud", ex);
                    try
                    {
                        await WriteAsync(stream, 500, ErrorJson($"Error interno: {ex.Message}")).ConfigureAwait(false);
                    }
                    catch
                    {
                        // ignored
                    }
                }
            }
        }

        private sealed class HttpRequest
        {
            public string Method { get; set; } = "";
            public string Path { get; set; } = "";
            public Dictionary<string, string> Headers { get; } =
                new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
            public string Body { get; set; } = "";
        }

        private static async Task<HttpRequest?> ReadRequestAsync(NetworkStream stream)
        {
            var buffer = new byte[MaxHeaderBytes];
            var total = 0;
            var headerEnd = -1;

            while (total < buffer.Length)
            {
                var read = await stream.ReadAsync(buffer, total, buffer.Length - total).ConfigureAwait(false);
                if (read <= 0)
                {
                    return null;
                }
                total += read;
                headerEnd = IndexOfHeaderEnd(buffer, total);
                if (headerEnd >= 0)
                {
                    break;
                }
            }

            if (headerEnd < 0)
            {
                return null;
            }

            var headerText = Encoding.ASCII.GetString(buffer, 0, headerEnd);
            var lines = headerText.Split(new[] { "\r\n" }, StringSplitOptions.None);
            if (lines.Length == 0)
            {
                return null;
            }

            var requestLine = lines[0].Split(' ');
            if (requestLine.Length < 2)
            {
                return null;
            }

            var request = new HttpRequest
            {
                Method = requestLine[0],
                Path = requestLine[1].Split('?')[0].TrimEnd('/'),
            };
            if (request.Path.Length == 0)
            {
                request.Path = "/";
            }

            for (var i = 1; i < lines.Length; i++)
            {
                var separator = lines[i].IndexOf(':');
                if (separator > 0)
                {
                    request.Headers[lines[i].Substring(0, separator).Trim()] =
                        lines[i].Substring(separator + 1).Trim();
                }
            }

            var contentLength = 0;
            if (request.Headers.TryGetValue("Content-Length", out var lengthText))
            {
                int.TryParse(lengthText, out contentLength);
            }
            if (contentLength < 0 || contentLength > MaxBodyBytes)
            {
                return null;
            }

            var bodyStart = headerEnd + 4;
            var alreadyRead = total - bodyStart;
            var bodyBytes = new byte[contentLength];
            if (alreadyRead > 0)
            {
                Array.Copy(buffer, bodyStart, bodyBytes, 0, Math.Min(alreadyRead, contentLength));
            }
            var remaining = contentLength - Math.Min(alreadyRead, contentLength);
            var offset = Math.Min(alreadyRead, contentLength);
            while (remaining > 0)
            {
                var read = await stream.ReadAsync(bodyBytes, offset, remaining).ConfigureAwait(false);
                if (read <= 0)
                {
                    break;
                }
                offset += read;
                remaining -= read;
            }
            request.Body = Encoding.UTF8.GetString(bodyBytes, 0, offset);
            return request;
        }

        private static int IndexOfHeaderEnd(byte[] buffer, int length)
        {
            for (var i = 0; i + 3 < length; i++)
            {
                if (buffer[i] == '\r' && buffer[i + 1] == '\n' &&
                    buffer[i + 2] == '\r' && buffer[i + 3] == '\n')
                {
                    return i;
                }
            }
            return -1;
        }

        private bool IsAuthorized(Dictionary<string, string> headers)
        {
            if (string.IsNullOrWhiteSpace(_settings.Token))
            {
                return false;
            }
            headers.TryGetValue("X-Ingenia-Token", out var provided);
            return FixedTimeEquals(provided ?? "", _settings.Token);
        }

        private static bool FixedTimeEquals(string a, string b)
        {
            var left = Encoding.UTF8.GetBytes(a);
            var right = Encoding.UTF8.GetBytes(b);
            if (left.Length != right.Length)
            {
                return false;
            }
#if NET8
            return CryptographicOperations.FixedTimeEquals(left, right);
#else
            var diff = 0;
            for (var i = 0; i < left.Length; i++)
            {
                diff |= left[i] ^ right[i];
            }
            return diff == 0;
#endif
        }

        private static string ErrorJson(string message) =>
            JsonSerializer.Serialize(BridgeResponse.Failure(message));

        private static async Task WriteAsync(NetworkStream stream, int statusCode, string json)
        {
            var body = Encoding.UTF8.GetBytes(json);
            var reason = statusCode switch
            {
                200 => "OK",
                400 => "Bad Request",
                401 => "Unauthorized",
                404 => "Not Found",
                405 => "Method Not Allowed",
                _ => "Internal Server Error",
            };
            var header =
                $"HTTP/1.1 {statusCode} {reason}\r\n" +
                "Content-Type: application/json; charset=utf-8\r\n" +
                $"Content-Length: {body.Length}\r\n" +
                "Connection: close\r\n\r\n";
            var headerBytes = Encoding.ASCII.GetBytes(header);
            await stream.WriteAsync(headerBytes, 0, headerBytes.Length).ConfigureAwait(false);
            await stream.WriteAsync(body, 0, body.Length).ConfigureAwait(false);
            await stream.FlushAsync().ConfigureAwait(false);
        }
    }
}
