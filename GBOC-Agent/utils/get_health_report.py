
import json
import logging
import os
from contextlib import redirect_stdout, redirect_stderr

# Suppress verbose logging from the application's core during report generation
logging.basicConfig(level=logging.FATAL)

def generate_report():
    """
    Initializes the application's core and uses its internal
    analyzer to generate a system health report.
    This is the most reliable way to get statistics as it uses the
    application's own logic and database connections.
    """
    report_data = {}
    try:
        # The application's core is noisy on startup, so suppress output
        with open(os.devnull, 'w') as f, redirect_stdout(f), redirect_stderr(f):
            from shared_core import get_shared_core
            core = get_shared_core()

        if hasattr(core, 'error_analyzer') and core.error_analyzer:
            # This method queries the DB and calculates success rates, etc.
            report_data = core.error_analyzer.get_system_health_report()
        else:
            report_data["error"] = "ErrorAnalyzer engine not found in SharedCore."

    except Exception as e:
        report_data["error"] = f"An exception occurred: {str(e)}"
    
    finally:
        # Cleanly shut down the core to release database locks and stop threads
        if 'core' in locals() and hasattr(core, 'shutdown'):
            with open(os.devnull, 'w') as f, redirect_stdout(f), redirect_stderr(f):
                core.shutdown()

    return report_data

if __name__ == "__main__":
    final_report = generate_report()
    print(json.dumps(final_report, indent=4))
