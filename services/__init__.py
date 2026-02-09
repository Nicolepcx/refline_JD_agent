# Services package
# Lazy imports — avoid pulling in heavy dependencies (art, ruler, etc.)
# on every `from services.X import Y` call.


def __getattr__(name):
    if name == "generate_full_job_description":
        from .job_service import generate_full_job_description
        return generate_full_job_description
    if name == "generate_job_section":
        from .job_service import generate_job_section
        return generate_job_section
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["generate_full_job_description", "generate_job_section"]

