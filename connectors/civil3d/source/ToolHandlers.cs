using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Reflection;
using System.Text.Json;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.Civil.ApplicationServices;
using Autodesk.Civil.DatabaseServices;
using Autodesk.Civil.DatabaseServices.Styles;
using AcApp = Autodesk.AutoCAD.ApplicationServices;
using AcDb = Autodesk.AutoCAD.DatabaseServices;
using AcDoc = Autodesk.AutoCAD.ApplicationServices.Document;
using AcTransaction = Autodesk.AutoCAD.DatabaseServices.Transaction;

namespace Ingenia.Bridge
{
    internal static class ToolHandlers
    {
        private delegate HandlerResult Handler(
            JsonElement args, AcDoc doc, AcTransaction tr);

        private static readonly Dictionary<string, Handler> Handlers =
            new Dictionary<string, Handler>(StringComparer.OrdinalIgnoreCase)
            {
                ["get_civil3d_status"] = (a, d, t) => Status(d),
                ["get_active_drawing_info"] = (a, d, t) => Status(d),
                ["list_drawing_objects"] = ListDrawingObjects,
                ["inspect_surface"] = InspectSurface,
                ["list_alignments"] = ListAlignments,
                ["create_surface"] = CreateSurface,
                ["generate_contours"] = GenerateContours,
                ["create_alignment_from_polyline"] = CreateAlignmentFromPolyline,
                ["generate_profile"] = GenerateProfile,
                ["calculate_volumes"] = CalculateVolumes,
            };

        public static bool IsKnown(string tool) => Handlers.ContainsKey(tool);

        public static HandlerResult Dispatch(
            string tool, JsonElement args, AcDoc doc, AcTransaction tr)
        {
            if (!Handlers.TryGetValue(tool, out var handler))
            {
                return HandlerResult.Failure($"Herramienta no permitida: {tool}");
            }

            try
            {
                return handler(args, doc, tr);
            }
            catch (Exception ex)
            {
                Log.Error($"Herramienta {tool} fallo", ex);
                return HandlerResult.Failure($"{ex.GetType().Name}: {ex.Message}");
            }
        }

        // ------------------------------------------------------------ status
        private static HandlerResult Status(AcDoc doc)
        {
            var db = doc.Database;
            var data = new Dictionary<string, object?>
            {
                ["drawing"] = new Dictionary<string, object?>
                {
                    ["name"] = doc.Name,
                    ["path"] = db.Filename,
                    ["units"] = db.Insunits.ToString(),
                    ["acadVersion"] = AcApp.Application.Version.ToString(),
                    ["civilVersion"] = CivilVersion(),
                },
                ["plugin"] = "IngeniaBridge",
                ["pluginVersion"] = typeof(ToolHandlers).Assembly.GetName().Version?.ToString(),
            };
            return HandlerResult.Success(data);
        }

        private static string CivilVersion()
        {
            try
            {
                var asm = Assembly.Load("AeccDbMgd");
                return asm.GetName().Version?.ToString() ?? "desconocida";
            }
            catch
            {
                return "desconocida";
            }
        }

        // ----------------------------------------------------------- objects
        private static HandlerResult ListDrawingObjects(
            JsonElement args, AcDoc doc, AcTransaction tr)
        {
            var type = Str(args, "object_type") ?? "all";
            var limit = Int(args, "limit") ?? 100;
            var db = doc.Database;
            var civ = CivilDocument.GetCivilDocument(db);
            var objects = new List<Dictionary<string, object?>>();

            void Add(string kind, string name, string handle)
            {
                if (objects.Count >= limit)
                {
                    return;
                }
                objects.Add(new Dictionary<string, object?>
                {
                    ["type"] = kind,
                    ["name"] = name,
                    ["handle"] = handle,
                });
            }

            if (type is "all" or "surface")
            {
                foreach (ObjectId id in civ.GetSurfaceIds())
                {
                    if (!id.IsValid || id.IsErased)
                    {
                        continue;
                    }
                    var surface = tr.GetObject(id, OpenMode.ForRead) as Surface;
                    if (surface != null)
                    {
                        Add("surface", surface.Name, surface.Handle.ToString());
                    }
                }
            }

            if (type is "all" or "alignment")
            {
                foreach (ObjectId id in civ.GetAlignmentIds())
                {
                    var alignment = tr.GetObject(id, OpenMode.ForRead) as Alignment;
                    if (alignment != null)
                    {
                        Add("alignment", alignment.Name, alignment.Handle.ToString());
                    }
                }
            }

            if (type is "all" or "profile")
            {
                foreach (ObjectId id in civ.GetAlignmentIds())
                {
                    var alignment = tr.GetObject(id, OpenMode.ForRead) as Alignment;
                    if (alignment == null)
                    {
                        continue;
                    }
                    foreach (ObjectId profileId in alignment.GetProfileIds())
                    {
                        var profile = tr.GetObject(profileId, OpenMode.ForRead) as Profile;
                        if (profile != null)
                        {
                            Add("profile", profile.Name, profile.Handle.ToString());
                        }
                    }
                }
            }

            if (type is "all" or "point" or "polyline" or "text")
            {
                var blockTable = (BlockTable)tr.GetObject(db.BlockTableId, OpenMode.ForRead);
                var modelSpace = (BlockTableRecord)tr.GetObject(
                    blockTable[BlockTableRecord.ModelSpace], OpenMode.ForRead);

                foreach (ObjectId id in modelSpace)
                {
                    if (objects.Count >= limit)
                    {
                        break;
                    }
                    var entity = tr.GetObject(id, OpenMode.ForRead) as Entity;
                    if (entity == null)
                    {
                        continue;
                    }
                    var kind = Classify(entity);
                    if (kind == null)
                    {
                        continue;
                    }
                    if (type != "all" && type != kind)
                    {
                        continue;
                    }
                    Add(kind, entity.GetType().Name, entity.Handle.ToString());
                }
            }

            return HandlerResult.Success(new Dictionary<string, object?>
            {
                ["drawing"] = doc.Name,
                ["units"] = db.Insunits.ToString(),
                ["filter"] = type,
                ["count"] = objects.Count,
                ["objects"] = objects,
            });
        }

        private static string? Classify(Entity entity)
        {
            var name = entity.GetType().Name;
            if (name == "CogoPoint")
            {
                return "point";
            }
            if (name is "Polyline" or "Polyline2d" or "Polyline3d")
            {
                return "polyline";
            }
            if (name is "DBText" or "MText")
            {
                return "text";
            }
            return null;
        }

        // ---------------------------------------------------------- surfaces
        private static HandlerResult InspectSurface(
            JsonElement args, AcDoc doc, AcTransaction tr)
        {
            var name = Str(args, "surface_name");
            if (string.IsNullOrWhiteSpace(name))
            {
                return HandlerResult.Failure("Falta surface_name.");
            }

            var civ = CivilDocument.GetCivilDocument(doc.Database);
            var surface = FindSurface(civ, tr, name);
            if (surface == null)
            {
                return HandlerResult.Failure($"No existe una superficie llamada '{name}'.");
            }

            var styleName = "";
            if (surface.StyleId != ObjectId.Null)
            {
                var style = tr.GetObject(surface.StyleId, OpenMode.ForRead) as SurfaceStyle;
                styleName = style?.Name ?? "";
            }

            return HandlerResult.Success(new Dictionary<string, object?>
            {
                ["name"] = surface.Name,
                ["description"] = surface.Description,
                ["handle"] = surface.Handle.ToString(),
                ["style"] = styleName,
                ["elevationMin"] = surface.ElevationMin,
                ["elevationMax"] = surface.ElevationMax,
                ["vertices"] = surface.NumberOfVertices,
                ["triangles"] = surface.NumberOfTriangles,
                ["area2D"] = surface.Area2D,
                ["area3D"] = surface.Area3D,
            });
        }

        private static HandlerResult CreateSurface(
            JsonElement args, AcDoc doc, AcTransaction tr)
        {
            var name = Str(args, "name");
            if (string.IsNullOrWhiteSpace(name))
            {
                return HandlerResult.Failure("Falta el nombre de la superficie.");
            }

            var civ = CivilDocument.GetCivilDocument(doc.Database);
            if (FindSurface(civ, tr, name) != null)
            {
                return HandlerResult.Failure($"Ya existe una superficie llamada '{name}'.");
            }

            var surface = TinSurface.Create(doc.Database, name);
            surface.Description = Str(args, "description") ?? "";

            var styleName = Str(args, "style");
            if (!string.IsNullOrWhiteSpace(styleName))
            {
                var styleId = FindStyleId(civ, tr, styleName, StyleKind.Surface);
                if (styleId == ObjectId.Null)
                {
                    return HandlerResult.Failure($"No existe el estilo de superficie '{styleName}'.");
                }
                surface.StyleId = styleId;
            }

            return HandlerResult.Success(new Dictionary<string, object?>
            {
                ["name"] = surface.Name,
                ["handle"] = surface.Handle.ToString(),
                ["style"] = surface.StyleId.ToString(),
                ["verified"] = FindSurface(civ, tr, name) != null,
            });
        }

        private static HandlerResult GenerateContours(
            JsonElement args, AcDoc doc, AcTransaction tr)
        {
            var name = Str(args, "surface_name");
            var major = Dbl(args, "major_interval");
            var minor = Dbl(args, "minor_interval") ?? 0;
            if (string.IsNullOrWhiteSpace(name) || major == null || major <= 0)
            {
                return HandlerResult.Failure("Se requiere surface_name y major_interval > 0.");
            }
            if (minor < 0)
            {
                return HandlerResult.Failure("minor_interval no puede ser negativo.");
            }

            var civ = CivilDocument.GetCivilDocument(doc.Database);
            var surface = FindSurface(civ, tr, name);
            if (surface == null)
            {
                return HandlerResult.Failure($"No existe una superficie llamada '{name}'.");
            }

            var style = tr.GetObject(surface.StyleId, OpenMode.ForWrite) as SurfaceStyle;
            if (style == null)
            {
                return HandlerResult.Failure("La superficie no tiene un estilo editable.");
            }

            // The contour interval API differs between Civil 3D releases. We probe
            // documented candidate members instead of hard-coding a name that may
            // not exist, and we verify the value afterwards. If the members are not
            // available we fail explicitly; we never report a false success.
            object? plan = null;
            foreach (var methodName in new[] { "GetContourStylePlan", "GetContourStyleModel" })
            {
                var method = style.GetType().GetMethod(methodName, Type.EmptyTypes);
                if (method != null)
                {
                    plan = method.Invoke(style, null);
                    if (plan != null)
                    {
                        break;
                    }
                }
            }

            if (plan == null)
            {
                return HandlerResult.Failure(
                    "Esta version de la API de Civil 3D no expone los intervalos de contorno por codigo. " +
                    "No se modifico el dibujo. Configura el estilo manualmente.");
            }

            if (!TrySetNumber(plan, new[] { "MajorInterval", "MajorContourInterval" }, major.Value) ||
                !TrySetNumber(plan, new[] { "MinorInterval", "MinorContourInterval" }, minor))
            {
                return HandlerResult.Failure(
                    "La API de contornos no expone MajorInterval/MinorInterval. " +
                    "No se modifico el dibujo.");
            }

            var verifyMajor = TryGetNumber(plan, new[] { "MajorInterval", "MajorContourInterval" });
            var verifyMinor = TryGetNumber(plan, new[] { "MinorInterval", "MinorContourInterval" });
            var verified = verifyMajor.HasValue &&
                           Math.Abs(verifyMajor.Value - major.Value) < 1e-6 &&
                           (!verifyMinor.HasValue || Math.Abs(verifyMinor.Value - minor) < 1e-6);

            if (!verified)
            {
                return HandlerResult.Failure(
                    "Los intervalos no se pudieron verificar tras aplicarlos. " +
                    "Se revirtio la transaccion.");
            }

            return HandlerResult.Success(new Dictionary<string, object?>
            {
                ["surface"] = surface.Name,
                ["majorInterval"] = verifyMajor,
                ["minorInterval"] = verifyMinor,
                ["verified"] = true,
            });
        }

        // -------------------------------------------------------- alignments
        private static HandlerResult ListAlignments(
            JsonElement args, AcDoc doc, AcTransaction tr)
        {
            var civ = CivilDocument.GetCivilDocument(doc.Database);
            var items = new List<Dictionary<string, object?>>();
            foreach (ObjectId id in civ.GetAlignmentIds())
            {
                var alignment = tr.GetObject(id, OpenMode.ForRead) as Alignment;
                if (alignment == null)
                {
                    continue;
                }
                items.Add(new Dictionary<string, object?>
                {
                    ["name"] = alignment.Name,
                    ["handle"] = alignment.Handle.ToString(),
                    ["length"] = alignment.Length,
                    ["startStation"] = alignment.StartingStation,
                    ["endStation"] = alignment.EndingStation,
                    ["profiles"] = alignment.GetProfileIds().Count,
                });
            }

            return HandlerResult.Success(new Dictionary<string, object?>
            {
                ["count"] = items.Count,
                ["alignments"] = items,
            });
        }

        private static HandlerResult CreateAlignmentFromPolyline(
            JsonElement args, AcDoc doc, AcTransaction tr)
        {
            var handleText = Str(args, "polyline_handle");
            var name = Str(args, "name");
            if (string.IsNullOrWhiteSpace(handleText) || string.IsNullOrWhiteSpace(name))
            {
                return HandlerResult.Failure("Se requiere polyline_handle y name.");
            }

            if (!long.TryParse(handleText, NumberStyles.HexNumber, CultureInfo.InvariantCulture, out var handleValue))
            {
                return HandlerResult.Failure("polyline_handle debe ser un handle hexadecimal valido.");
            }

            var handle = new Handle(handleValue);
            if (!doc.Database.TryGetObjectId(handle, out var polylineId) ||
                polylineId == ObjectId.Null ||
                polylineId.IsErased)
            {
                return HandlerResult.Failure($"No existe una entidad con handle '{handleText}'.");
            }

            var entity = tr.GetObject(polylineId, OpenMode.ForRead);
            var typeName = entity.GetType().Name;
            if (typeName is not ("Polyline" or "Polyline2d" or "Polyline3d"))
            {
                return HandlerResult.Failure(
                    $"La entidad {handleText} es '{typeName}', no una polilinea.");
            }

            var civ = CivilDocument.GetCivilDocument(doc.Database);
            foreach (ObjectId id in civ.GetAlignmentIds())
            {
                var existing = tr.GetObject(id, OpenMode.ForRead) as Alignment;
                if (existing != null && string.Equals(existing.Name, name, StringComparison.OrdinalIgnoreCase))
                {
                    return HandlerResult.Failure($"Ya existe un alineamiento llamado '{name}'.");
                }
            }

            var styleName = Str(args, "style") ?? "";
            var layerId = doc.Database.Clayer;

            var alignment = TryCreateAlignmentFromPolyline(
                civ, doc.Database, polylineId, layerId, name, styleName);

            if (alignment == null)
            {
                return HandlerResult.Failure(
                    "La API de esta version no expone un metodo verificado para crear alineamientos " +
                    "desde una polilinea. No se modifico el dibujo. Usa los comandos de Civil 3D.");
            }

            return HandlerResult.Success(new Dictionary<string, object?>
            {
                ["name"] = alignment.Name,
                ["handle"] = alignment.Handle.ToString(),
                ["sourcePolyline"] = handleText,
                ["verified"] = !alignment.IsErased,
            });
        }

        private static Alignment? TryCreateAlignmentFromPolyline(
            CivilDocument civ,
            Database db,
            ObjectId polylineId,
            ObjectId layerId,
            string name,
            string styleName)
        {
            var methods = typeof(Alignment)
                .GetMethods(BindingFlags.Public | BindingFlags.Static)
                .Where(m => m.Name == "CreateFromPolyline")
                .ToList();

            string? lastError = null;
            foreach (var method in methods)
            {
                var parameters = method.GetParameters();
                var values = new object?[parameters.Length];
                var stringIndex = 0;
                var objectIdIndex = 0;
                var buildable = true;

                for (var i = 0; i < parameters.Length; i++)
                {
                    var type = parameters[i].ParameterType;
                    if (type == typeof(CivilDocument))
                    {
                        values[i] = civ;
                    }
                    else if (type == typeof(Database))
                    {
                        values[i] = db;
                    }
                    else if (type == typeof(string))
                    {
                        values[i] = stringIndex++ switch
                        {
                            0 => name,
                            1 => styleName,
                            _ => "",
                        };
                    }
                    else if (type == typeof(ObjectId))
                    {
                        values[i] = objectIdIndex++ switch
                        {
                            0 => polylineId,
                            1 => layerId,
                            _ => ObjectId.Null,
                        };
                    }
                    else if (type == typeof(bool))
                    {
                        values[i] = false;
                    }
                    else
                    {
                        buildable = false;
                        break;
                    }
                }

                if (!buildable)
                {
                    continue;
                }

                try
                {
                    var result = method.Invoke(null, values);
                    if (result is Alignment alignment)
                    {
                        return alignment;
                    }
                }
                catch (TargetInvocationException ex)
                {
                    lastError = ex.InnerException?.Message ?? ex.Message;
                }
                catch (Exception ex)
                {
                    lastError = ex.Message;
                }
            }

            if (!string.IsNullOrEmpty(lastError))
            {
                Log.Warn($"CreateFromPolyline no aplicable: {lastError}");
            }
            return null;
        }

        // ---------------------------------------------------------- profiles
        private static HandlerResult GenerateProfile(
            JsonElement args, AcDoc doc, AcTransaction tr)
        {
            var alignmentName = Str(args, "alignment_name");
            var surfaceName = Str(args, "surface_name");
            if (string.IsNullOrWhiteSpace(alignmentName) || string.IsNullOrWhiteSpace(surfaceName))
            {
                return HandlerResult.Failure("Se requiere alignment_name y surface_name.");
            }

            var civ = CivilDocument.GetCivilDocument(doc.Database);
            var alignment = FindAlignment(civ, tr, alignmentName);
            if (alignment == null)
            {
                return HandlerResult.Failure($"No existe un alineamiento llamado '{alignmentName}'.");
            }
            var surface = FindSurface(civ, tr, surfaceName);
            if (surface == null)
            {
                return HandlerResult.Failure($"No existe una superficie llamada '{surfaceName}'.");
            }

            var profileName = Str(args, "name");
            if (string.IsNullOrWhiteSpace(profileName))
            {
                profileName = $"{alignmentName} - Perfil";
            }

            var profile = Profile.CreateFromSurface(profileName, alignment.ObjectId, surface.ObjectId);
            if (profile == null)
            {
                return HandlerResult.Failure("Civil 3D no devolvio el perfil creado.");
            }

            return HandlerResult.Success(new Dictionary<string, object?>
            {
                ["name"] = profile.Name,
                ["handle"] = profile.Handle.ToString(),
                ["alignment"] = alignmentName,
                ["surface"] = surfaceName,
                ["verified"] = !profile.IsErased,
            });
        }

        // ----------------------------------------------------------- volumes
        private static HandlerResult CalculateVolumes(
            JsonElement args, AcDoc doc, AcTransaction tr)
        {
            var baseName = Str(args, "base_surface");
            var comparisonName = Str(args, "comparison_surface");
            if (string.IsNullOrWhiteSpace(baseName) || string.IsNullOrWhiteSpace(comparisonName))
            {
                return HandlerResult.Failure("Se requiere base_surface y comparison_surface.");
            }

            var civ = CivilDocument.GetCivilDocument(doc.Database);
            var baseSurface = FindSurface(civ, tr, baseName);
            var comparison = FindSurface(civ, tr, comparisonName);
            if (baseSurface == null)
            {
                return HandlerResult.Failure($"No existe la superficie '{baseName}'.");
            }
            if (comparison == null)
            {
                return HandlerResult.Failure($"No existe la superficie '{comparisonName}'.");
            }

            var volumeType = typeof(TinVolumeSurface);
            var create = volumeType
                .GetMethods(BindingFlags.Public | BindingFlags.Static)
                .FirstOrDefault(m =>
                    m.Name == "Create" &&
                    m.GetParameters().Length == 4 &&
                    m.GetParameters()[0].ParameterType == typeof(Database));

            if (create == null)
            {
                return HandlerResult.Failure(
                    "La API de esta version no expone TinVolumeSurface.Create con la firma esperada. " +
                    "No se calculo ningun volumen.");
            }

            var tempName = $"INGENIA_VOL_{DateTime.Now:HHmmss}";
            object? volumeSurface = null;
            try
            {
                volumeSurface = create.Invoke(
                    null,
                    new object[] { doc.Database, tempName, baseSurface.ObjectId, comparison.ObjectId });

                if (volumeSurface == null)
                {
                    return HandlerResult.Failure("No se pudo crear la superficie de volumen temporal.");
                }

                var props = volumeSurface.GetType()
                    .GetMethod("GetVolumeProperties", Type.EmptyTypes)?
                    .Invoke(volumeSurface, null);

                if (props == null)
                {
                    return HandlerResult.Failure(
                        "La API no expone GetVolumeProperties; no se puede verificar el volumen.");
                }

                var cut = TryGetNumber(props, new[] { "CutVolume" });
                var fill = TryGetNumber(props, new[] { "FillVolume" });
                var net = TryGetNumber(props, new[] { "NetVolume" });
                if (cut == null && fill == null)
                {
                    return HandlerResult.Failure(
                        "La API de volumenes no expone CutVolume/FillVolume; no se reporta resultado.");
                }

                if (volumeSurface is Entity entity)
                {
                    entity.Erase();
                }

                return HandlerResult.Success(new Dictionary<string, object?>
                {
                    ["baseSurface"] = baseName,
                    ["comparisonSurface"] = comparisonName,
                    ["cutVolume"] = cut,
                    ["fillVolume"] = fill,
                    ["netVolume"] = net,
                    ["units"] = "unidades del dibujo al cubo",
                    ["verified"] = true,
                });
            }
            finally
            {
                if (volumeSurface is DBObject dbObject && !dbObject.IsErased)
                {
                    try
                    {
                        dbObject.Erase();
                    }
                    catch
                    {
                        // best effort
                    }
                }
            }
        }

        // ----------------------------------------------------------- helpers
        private enum StyleKind
        {
            Surface,
            Alignment,
        }

        private static Surface? FindSurface(
            CivilDocument civ, AcTransaction tr, string name)
        {
            foreach (ObjectId id in civ.GetSurfaceIds())
            {
                var surface = tr.GetObject(id, OpenMode.ForRead) as Surface;
                if (surface != null &&
                    string.Equals(surface.Name, name, StringComparison.OrdinalIgnoreCase))
                {
                    return surface;
                }
            }
            return null;
        }

        private static Alignment? FindAlignment(
            CivilDocument civ, AcTransaction tr, string name)
        {
            foreach (ObjectId id in civ.GetAlignmentIds())
            {
                var alignment = tr.GetObject(id, OpenMode.ForRead) as Alignment;
                if (alignment != null &&
                    string.Equals(alignment.Name, name, StringComparison.OrdinalIgnoreCase))
                {
                    return alignment;
                }
            }
            return null;
        }

        private static ObjectId FindStyleId(
            CivilDocument civ, AcTransaction tr, string name, StyleKind kind)
        {
            if (kind == StyleKind.Surface)
            {
                foreach (ObjectId id in civ.Styles.SurfaceStyles)
                {
                    var style = tr.GetObject(id, OpenMode.ForRead) as SurfaceStyle;
                    if (style != null &&
                        string.Equals(style.Name, name, StringComparison.OrdinalIgnoreCase))
                    {
                        return id;
                    }
                }
            }
            else
            {
                foreach (ObjectId id in civ.Styles.AlignmentStyles)
                {
                    var style = tr.GetObject(id, OpenMode.ForRead) as AlignmentStyle;
                    if (style != null &&
                        string.Equals(style.Name, name, StringComparison.OrdinalIgnoreCase))
                    {
                        return id;
                    }
                }
            }
            return ObjectId.Null;
        }

        private static string? Str(JsonElement args, string name)
        {
            if (args.ValueKind != JsonValueKind.Object ||
                !args.TryGetProperty(name, out var value))
            {
                return null;
            }
            return value.ValueKind == JsonValueKind.String ? value.GetString() : null;
        }

        private static double? Dbl(JsonElement args, string name)
        {
            if (args.ValueKind != JsonValueKind.Object ||
                !args.TryGetProperty(name, out var value))
            {
                return null;
            }
            if (value.ValueKind == JsonValueKind.Number && value.TryGetDouble(out var number))
            {
                return number;
            }
            if (value.ValueKind == JsonValueKind.String &&
                double.TryParse(value.GetString(), NumberStyles.Any, CultureInfo.InvariantCulture, out var parsed))
            {
                return parsed;
            }
            return null;
        }

        private static int? Int(JsonElement args, string name)
        {
            var value = Dbl(args, name);
            return value.HasValue ? (int)value.Value : null;
        }

        private static bool TrySetNumber(object target, string[] names, double value)
        {
            var type = target.GetType();
            foreach (var name in names)
            {
                var property = type.GetProperty(name);
                if (property != null && property.CanWrite)
                {
                    property.SetValue(target, Convert.ChangeType(value, property.PropertyType, CultureInfo.InvariantCulture));
                    return true;
                }
            }
            return false;
        }

        private static double? TryGetNumber(object target, string[] names)
        {
            var type = target.GetType();
            foreach (var name in names)
            {
                var property = type.GetProperty(name);
                if (property == null)
                {
                    continue;
                }
                var raw = property.GetValue(target);
                if (raw != null)
                {
                    return Convert.ToDouble(raw, CultureInfo.InvariantCulture);
                }
            }
            return null;
        }
    }
}
