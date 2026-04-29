from herbie import Herbie
from datetime import datetime, timedelta

# Use yesterday's 00Z run to ensure it's published
run_date = (datetime.utcnow() - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)

H = Herbie(
    run_date,
    model="gefs",
    product="atmos.5",
    member="mean",
    fxx=6,
)

print(f"Source URL: {H.grib}")
local_path = H.download()
print(f"Downloaded to: {local_path}")
