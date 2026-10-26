using System;
using System.Collections.Concurrent;
using System.Threading.Tasks;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;

namespace Ingenia.Bridge
{
    /// <summary>
    /// Civil 3D objects may only be touched from AutoCAD's main thread.
    /// Requests arriving on the HTTP thread are queued here and drained on
    /// the Application.Idle event inside a document lock and transaction.
    /// </summary>
    internal static class MainThreadDispatcher
    {
        private sealed class WorkItem
        {
            public Func<Document, Transaction, HandlerResult> Work { get; set; } = null!;
            public TaskCompletionSource<HandlerResult> Completion { get; } =
                new TaskCompletionSource<HandlerResult>(TaskCreationOptions.RunContinuationsAsynchronously);
        }

        private static readonly ConcurrentQueue<WorkItem> Queue = new ConcurrentQueue<WorkItem>();
        private static readonly object Sync = new object();
        private static bool _hooked;

        public static void Start()
        {
            lock (Sync)
            {
                if (_hooked)
                {
                    return;
                }
                Application.Idle += OnIdle;
                _hooked = true;
                Log.Info("Dispatcher enlazado a Application.Idle.");
            }
        }

        public static void Stop()
        {
            lock (Sync)
            {
                if (!_hooked)
                {
                    return;
                }
                Application.Idle -= OnIdle;
                _hooked = false;
            }
        }

        public static Task<HandlerResult> Enqueue(Func<Document, Transaction, HandlerResult> work)
        {
            var item = new WorkItem { Work = work };
            Queue.Enqueue(item);
            return item.Completion.Task;
        }

        private static void OnIdle(object? sender, EventArgs e)
        {
            while (Queue.TryDequeue(out var item))
            {
                var doc = Application.DocumentManager.MdiActiveDocument;
                if (doc == null)
                {
                    item.Completion.TrySetResult(
                        HandlerResult.Failure("No hay un dibujo activo en Civil 3D."));
                    continue;
                }

                try
                {
                    using (doc.LockDocument())
                    using (var tr = doc.Database.TransactionManager.StartTransaction())
                    {
                        HandlerResult result;
                        try
                        {
                            result = item.Work(doc, tr);
                        }
                        catch (Exception ex)
                        {
                            Log.Error("Fallo ejecutando herramienta", ex);
                            tr.Abort();
                            item.Completion.TrySetResult(
                                HandlerResult.Failure($"{ex.GetType().Name}: {ex.Message}"));
                            continue;
                        }

                        if (result.Ok)
                        {
                            tr.Commit();
                        }
                        else
                        {
                            tr.Abort();
                        }
                        item.Completion.TrySetResult(result);
                    }
                }
                catch (Exception ex)
                {
                    Log.Error("Fallo en el contexto de transaccion", ex);
                    item.Completion.TrySetResult(
                        HandlerResult.Failure($"{ex.GetType().Name}: {ex.Message}"));
                }
            }
        }
    }
}
