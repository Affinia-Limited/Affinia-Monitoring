"""Resource-type monitor plugins.

Each Azure resource type is described by one ``AzureResourceMonitor`` subclass
declaring *data*, not code paths:

* which ARM types (and kinds / SKUs) it handles
* its metric catalogue (Azure metric name, unit, aggregation, dimension split)
* default health rules (warning / critical thresholds, overridable per organisation)
* predefined log queries
* metrics used for environment comparison
* a dashboard template built from reusable widgets

Adding a resource type means adding one subclass and registering it in
``app.services.monitors.registry``. See ``docs/adding-resource-types.md``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar, Literal

Operator = Literal["gt", "gte", "lt", "lte"]
Rollup = Literal["avg", "sum", "max", "min"]


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


@dataclass(frozen=True)
class MetricDef:
    #: Stable key used by widgets, health rules and the API (e.g. ``cpu``).
    key: str
    #: Azure Monitor metric name (e.g. ``CpuPercentage``).
    name: str
    label: str
    #: Display unit after ``scale``: percent | count | milliseconds | seconds | bytes | bytes_per_second | countps
    unit: str
    aggregation: str = "Average"
    namespace: str | None = None
    #: Dimension to split by (e.g. ``HttpStatusGroup``); produces one series per value.
    split_by: str | None = None
    #: Multiplier applied to raw values (e.g. 1000 to convert seconds to milliseconds).
    scale: float = 1.0
    #: ``self`` or ``related:<relation>`` when the metric lives on a related resource.
    target: str = "self"
    description: str = ""
    #: Some metrics only support coarse granularity (e.g. StorageUsed: 1 hour).
    min_interval_minutes: int | None = None


@dataclass(frozen=True)
class HealthRule:
    metric: str
    operator: Operator
    warning: float | None
    critical: float | None
    #: How far back to aggregate when evaluating.
    window_minutes: int = 15
    #: How to reduce the window's points to a single value.
    reducer: Rollup = "avg"
    description: str = ""


@dataclass(frozen=True)
class LogQueryDef:
    key: str
    title: str
    kql: str
    description: str = ""
    #: table | timechart
    visualization: str = "table"
    #: ``self`` or ``related:<relation>`` (e.g. Application Insights component).
    target: str = "self"
    #: Column holding a severity/level, enabling the severity filter.
    severity_column: str | None = None
    category: str = "Logs"


@dataclass(frozen=True)
class ComparisonMetric:
    metric: str
    #: How values are combined across resources within one environment.
    rollup: Rollup = "avg"
    label: str | None = None


@dataclass(frozen=True)
class Widget:
    type: str
    title: str
    width: int = 6
    config: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Section:
    title: str
    widgets: tuple[Widget, ...]


# ---- widget helpers keep templates short and uniform -----------------------------


def stat(metric: str, title: str, reducer: Rollup = "avg", width: int = 3) -> Widget:
    return Widget("metric_card", title, width, {"metric": metric, "reducer": reducer})


def gauge(metric: str, title: str, maximum: float = 100, width: int = 3) -> Widget:
    return Widget("gauge", title, width, {"metric": metric, "reducer": "avg", "max": maximum})


def line(title: str, *metrics: str, width: int = 6, stacked: bool = False) -> Widget:
    return Widget("line_chart", title, width, {"metrics": list(metrics), "stacked": stacked})


def area(title: str, *metrics: str, width: int = 6, stacked: bool = True) -> Widget:
    return Widget("area_chart", title, width, {"metrics": list(metrics), "stacked": stacked})


def bars(title: str, *metrics: str, width: int = 6, stacked: bool = True) -> Widget:
    return Widget("bar_chart", title, width, {"metrics": list(metrics), "stacked": stacked})


def log_table(query: str, title: str, width: int = 12) -> Widget:
    return Widget("log_table", title, width, {"query": query})


def log_chart(query: str, title: str, width: int = 6) -> Widget:
    return Widget("log_chart", title, width, {"query": query})


def health_card(width: int = 4) -> Widget:
    return Widget("resource_health", "Health", width, {})


def alerts_table(width: int = 8) -> Widget:
    return Widget("alert_table", "Alerts", width, {})


def children_table(title: str, relation: str, width: int = 12) -> Widget:
    return Widget("resource_table", title, width, {"relation": relation})


class AzureResourceMonitor:
    key: ClassVar[str]
    display_name: ClassVar[str]
    category: ClassVar[str] = "Other"
    #: Lower-cased ARM resource types handled by this monitor.
    resource_types: ClassVar[tuple[str, ...]] = ()
    template_version: ClassVar[int] = 1

    metrics: ClassVar[tuple[MetricDef, ...]] = ()
    health_rules: ClassVar[tuple[HealthRule, ...]] = ()
    log_queries: ClassVar[tuple[LogQueryDef, ...]] = ()
    comparison: ClassVar[tuple[ComparisonMetric, ...]] = ()
    #: Metric keys highlighted on the resource overview.
    summary_metrics: ClassVar[tuple[str, ...]] = ()

    def matches(self, resource_type: str, kind: str | None, sku: str | None) -> bool:
        return resource_type in self.resource_types

    def related(self, resource_type: str, azure_id: str, properties: dict[str, Any]) -> dict[str, str]:
        """Relation name -> lower-cased ARM id of related resources (e.g. the App Service Plan)."""
        return {}

    def sections(self) -> tuple[Section, ...]:
        """Default layout for monitors that only declare metrics. Override for curated dashboards."""
        if not self.metrics:
            return (Section("Overview", (health_card(width=4), alerts_table(width=8))),)
        summary = self.summary_metrics or tuple(m.key for m in self.metrics if not m.split_by)[:4]
        widgets: list[Widget] = []
        for key in summary[:4]:
            m = self.metric(key)
            if m is None:
                continue
            widgets.append(stat(key, m.label, "sum" if m.aggregation == "Total" else "avg"))
        widgets += [health_card(width=4), alerts_table(width=8)]
        for m in self.metrics:
            widgets.append(bars(m.label, m.key) if m.split_by else line(m.label, m.key))
        return (Section("Overview", tuple(widgets)),)

    # ---- derived helpers ----------------------------------------------------

    def metric(self, key: str) -> MetricDef | None:
        return next((m for m in self.metrics if m.key == key), None)

    def log_query(self, key: str) -> LogQueryDef | None:
        return next((q for q in self.log_queries if q.key == key), None)

    def _widget_config(self, widget: Widget) -> dict[str, Any]:
        config = dict(widget.config)
        # Single-metric widgets carry the metric's default health thresholds so the UI can colour
        # values by the same rules health evaluation uses (never by guesswork).
        rule = next((r for r in self.health_rules if r.metric == config.get("metric")), None)
        if rule is not None:
            config["thresholds"] = {"operator": rule.operator, "warning": rule.warning, "critical": rule.critical}
        return config

    def template(self) -> dict[str, Any]:
        return {
            "sections": [
                {
                    "title": section.title,
                    "widgets": [
                        {"type": w.type, "title": w.title, "width": w.width, "config": self._widget_config(w)}
                        for w in section.widgets
                    ],
                }
                for section in self.sections()
            ]
        }

    def validate(self) -> None:
        """Fail fast at start-up if a template references unknown metrics or queries."""
        metric_keys = {m.key for m in self.metrics}
        query_keys = {q.key for q in self.log_queries}
        for rule in self.health_rules:
            _check(rule.metric in metric_keys, f"{self.key}: health rule uses unknown metric {rule.metric}")
        for comp in self.comparison:
            _check(comp.metric in metric_keys, f"{self.key}: comparison uses unknown metric {comp.metric}")
        for key in self.summary_metrics:
            _check(key in metric_keys, f"{self.key}: summary uses unknown metric {key}")
        for section in self.sections():
            for widget in section.widgets:
                refs = list(widget.config.get("metrics", []))
                if "metric" in widget.config:
                    refs.append(widget.config["metric"])
                for ref in refs:
                    _check(ref in metric_keys, f"{self.key}: widget '{widget.title}' uses unknown metric {ref}")
                if "query" in widget.config:
                    _check(widget.config["query"] in query_keys, f"{self.key}: unknown log query")
