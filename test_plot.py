from prediction_integrity.engine import generate_monthly_calibration
from pathlib import Path

print("Generating monthly calibration with reliability plot...")
report = generate_monthly_calibration(month="2026-03")

plot_path = Path("logs/reliability_curve_2026_03.png")
if plot_path.exists():
    print(f"Success! Plot created at {plot_path} ({plot_path.stat().st_size} bytes)")
else:
    print("Failure: Plot file was not created.")
