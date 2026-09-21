// Says which data the dashboard is showing. An evaluation dataset carries planted
// anomalies; its cases must never be mistaken for real findings.
import { useMetrics } from "../api/hooks";

export function DatasetBanner() {
  const { data } = useMetrics();
  if (!data) return null;
  return (
    <>
      {data.evaluation_seed !== null && (
        <div className="banner" role="note">
          <strong>Evaluation dataset</strong> (seed {data.evaluation_seed}): it contains planted anomalies with a
          known answer key. These cases measure SpendGuard; they are not real findings.
        </div>
      )}
      {data.converted_from && (
        <div className="banner" role="note">
          Amounts were converted to ₹ from {data.converted_from} at a pinned rate.
        </div>
      )}
    </>
  );
}
