using System.Collections.Generic;
using System.Text.Json;

namespace Ingenia.Bridge
{
    internal sealed class BridgeRequest
    {
        public string Tool { get; set; } = "";
        public string RequestId { get; set; } = "";
        public JsonElement Args { get; set; }
    }

    internal sealed class BridgeResponse
    {
        public bool Ok { get; set; }
        public string Mode { get; set; } = "real";
        public string? Tool { get; set; }
        public string? RequestId { get; set; }
        public string? Error { get; set; }
        public object? Data { get; set; }

        public static BridgeResponse Failure(string error, string? tool = null, string? requestId = null) =>
            new BridgeResponse { Ok = false, Error = error, Tool = tool, RequestId = requestId };

        public static BridgeResponse Success(object? data) =>
            new BridgeResponse { Ok = true, Data = data };
    }

    internal sealed class HandlerResult
    {
        public bool Ok { get; set; }
        public string? Error { get; set; }
        public object? Data { get; set; }

        public static HandlerResult Success(object? data) => new HandlerResult { Ok = true, Data = data };
        public static HandlerResult Failure(string error) => new HandlerResult { Ok = false, Error = error };

        public Dictionary<string, object?> ToDictionary()
        {
            return new Dictionary<string, object?>
            {
                ["ok"] = Ok,
                ["error"] = Error,
                ["data"] = Data,
            };
        }
    }
}
