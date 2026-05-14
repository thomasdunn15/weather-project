SELECT 
    init_time,
    COUNT(DISTINCT member_id) as n_members,
    ROUND(AVG(daily_high)::numeric, 2) as mean_high,
    ROUND(STDDEV(daily_high)::numeric, 2) as spread,
    ROUND(MIN(daily_high)::numeric, 1) as min_high,
    ROUND(MAX(daily_high)::numeric, 1) as max_high
FROM (
    SELECT init_time, member_id, MAX(tmax_f) as daily_high
    FROM forecasts
    WHERE valid_time AT TIME ZONE 'America/New_York' >= '2026-05-14'::timestamp
      AND valid_time AT TIME ZONE 'America/New_York' <  '2026-05-15'::timestamp
      AND station_id = 'KNYC'
    GROUP BY init_time, member_id
) member_highs
GROUP BY init_time
ORDER BY init_time;