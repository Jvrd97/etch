"use client";
// [review:need-review] PHASE-02/68
// summary: desktop /health/[identifier] — one metric's daily series and the hours of a chosen day; the body is MetricDetail, shared with the phone shell

import { useParams } from "next/navigation";
import MetricDetail from "@/components/health/MetricDetail";

export default function HealthMetricPage() {
  const params = useParams<{ identifier: string }>();
  return (
    <MetricDetail
      identifier={decodeURIComponent(params.identifier)}
      backHref="/health"
    />
  );
}
