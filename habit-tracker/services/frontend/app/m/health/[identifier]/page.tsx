"use client";
// [review:need-review] PHASE-02/68
// summary: phone /m/health/[identifier] — twin of the desktop metric detail screen, the same MetricDetail body so the two shells cannot disagree on a number

import { useParams } from "next/navigation";
import MetricDetail from "@/components/health/MetricDetail";

export default function MobileHealthMetricPage() {
  const params = useParams<{ identifier: string }>();
  return (
    <MetricDetail
      identifier={decodeURIComponent(params.identifier)}
      backHref="/m/health"
    />
  );
}
