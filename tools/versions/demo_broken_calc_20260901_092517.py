def demo_broken_calc(a: str = "", b: str = "") -> dict:
    # Deliberately broken: no error handling, crashes on empty/invalid input
    result = int(a) + int(b)
    return {"success": True, "result": result}
