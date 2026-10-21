import importlib
for m in ["websocket", "websockets", "requests", "PIL", "bs4"]:
    try:
        mod = importlib.import_module(m)
        print(m, "OK", getattr(mod, "__version__", "?"))
    except Exception:
        print(m, "MISSING")
