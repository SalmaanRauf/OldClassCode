import React, { useState } from "react";

function badgeClass(kind) {
    if (kind === "BUYER") {
        return "border-[#8b7b5f] bg-[#efe8d8] text-[#55462d]";
    }
    return "border-slate-300 bg-slate-100 text-slate-700";
}

function postureClass(posture) {
    if (posture === "Immediate Re-engagement") {
        return "border-emerald-200 bg-emerald-50 text-emerald-800";
    }
    if (posture === "Expansion Opportunity") {
        return "border-amber-200 bg-amber-50 text-amber-900";
    }
    return "border-slate-200 bg-slate-50 text-slate-700";
}

function safeList(value) {
    return Array.isArray(value) ? value : [];
}

export default function MovementBrief() {
    const [expandedRowId, setExpandedRowId] = useState(null);
    const data = props || {};
    const rows = safeList(data.movement_rows);
    const detailsById = data.row_details_by_id || {};
    const actions = safeList(data.where_to_act);
    const stats = data.stats || {};
    const moveSummary = data.move_summary || {};

    const toggleExpanded = (rowId) => {
        setExpandedRowId((current) => (current === rowId ? null : rowId));
    };

    return (
        <section className="w-full overflow-hidden rounded-[28px] border border-[#d8cbbb] bg-[linear-gradient(180deg,#f6f0e8_0%,#f3ecdf_100%)] text-slate-900 shadow-[0_26px_90px_rgba(36,24,8,0.08)]">
            <div className="mx-auto max-w-7xl px-4 py-4 sm:px-6 sm:py-6">
                <header className="rounded-[24px] border border-[#e2d7c5] bg-white/75 px-4 py-4 shadow-sm backdrop-blur sm:px-6">
                    <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                        <div className="max-w-3xl">
                            <p className="text-[0.7rem] font-semibold uppercase tracking-[0.3em] text-[#6f5a42]">
                                People movement brief
                            </p>
                            <h1 className="mt-2 font-serif text-2xl tracking-[-0.04em] sm:text-3xl">
                                {data.title || "People Movement Brief"}
                            </h1>
                            <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-700">
                                {data.subtitle || ""}
                            </p>
                        </div>
                        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:min-w-[26rem]">
                            <StatCard label="Movers" value={stats.visible_rows ?? rows.length} />
                            <StatCard label="EXEC" value={stats.exec_rows ?? 0} />
                            <StatCard label="BUYER" value={stats.buyer_rows ?? 0} />
                            <StatCard label="Actions" value={stats.actions ?? actions.length} />
                        </div>
                    </div>
                </header>

                <main className="mt-4 grid gap-4">
                    <SectionCard title="Move Summary">
                        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_18rem]">
                            <div>
                                <p className="max-w-4xl text-sm leading-7 text-slate-700 whitespace-pre-line">
                                    {moveSummary.summary_text || "No move summary available."}
                                </p>
                            </div>
                            <div className="grid gap-3">
                                <Definition label="Person" value={moveSummary.person_name || "—"} />
                                <Definition label="Move" value={`${moveSummary.from_company || "—"} -> ${moveSummary.to_company || "—"}`} />
                                <Definition label="Target Role" value={moveSummary.new_role || "—"} />
                                <Definition label="Lookback" value={`${moveSummary.lookback_days || 180} days`} />
                                <Definition label="Scenario" value={moveSummary.synthetic_scenario ? "Synthetic" : "Live"} />
                                <Definition label="Warm Path" value={moveSummary.warm_intro_path_available ? "Yes" : "No"} />
                            </div>
                        </div>
                    </SectionCard>

                    <SectionCard title="Signal Summary">
                        {safeList(data.signal_summary).length ? (
                            <ul className="grid gap-2 sm:grid-cols-2">
                                {safeList(data.signal_summary).map((item, index) => (
                                    <li
                                        key={`${index}-${item}`}
                                        className="rounded-2xl border border-[#e5d9c7] bg-white/90 px-4 py-3 text-sm leading-6 text-slate-700"
                                    >
                                        {item}
                                    </li>
                                ))}
                            </ul>
                        ) : (
                            <p className="text-sm text-slate-600">No signal summary available.</p>
                        )}
                    </SectionCard>

                    <SectionCard title="Who Has Moved - And Where We Have Leverage">
                        <div className="hidden md:block">
                            <div className="overflow-x-auto rounded-[22px] border border-[#dccfbf] bg-white">
                                <table className="min-w-full border-collapse text-left">
                                    <caption className="sr-only">
                                        Executive and buyer movement table with inline leverage and proof details.
                                    </caption>
                                    <thead className="bg-[#f5efe4] text-[0.72rem] uppercase tracking-[0.22em] text-[#6f5a42]">
                                        <tr>
                                            {(data.table_columns || []).map((column) => (
                                                <th key={column} scope="col" className="whitespace-nowrap px-4 py-3 font-semibold">
                                                    {column}
                                                </th>
                                            ))}
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {rows.map((row) => {
                                            const detail = detailsById[row.row_id] || {};
                                            const expanded = expandedRowId === row.row_id;
                                            return (
                                                <React.Fragment key={row.row_id}>
                                                    <tr className="border-t border-[#ebdfd1] align-top hover:bg-[#faf6ef]">
                                                        <td className="px-4 py-4">
                                                            <span className={`inline-flex rounded-full border px-2.5 py-1 text-[0.72rem] font-semibold uppercase tracking-[0.18em] ${badgeClass(row.signal)}`}>
                                                                {row.signal}
                                                            </span>
                                                        </td>
                                                        <th scope="row" className="px-4 py-4 text-left font-medium text-slate-900">
                                                            {row.person_name}
                                                        </th>
                                                        <td className="px-4 py-4 text-sm text-slate-700">{row.previous_role}</td>
                                                        <td className="px-4 py-4 text-sm text-slate-700">{row.new_role}</td>
                                                        <td className="px-4 py-4 text-sm text-slate-700">{row.movement_type}</td>
                                                        <td className="px-4 py-4 text-sm text-slate-700">{row.known ? "Yes" : "No"}</td>
                                                        <td className="px-4 py-4 text-sm text-slate-700">{row.worked_with ? "Yes" : "No"}</td>
                                                        <td className="px-4 py-4 text-sm text-slate-700">{row.project_count}</td>
                                                        <td className="px-4 py-4 text-sm text-slate-700">{row.win_count}</td>
                                                        <td className="px-4 py-4 text-sm text-slate-700">{row.relationship_owner || "—"}</td>
                                                        <td className="px-4 py-4">
                                                            <span className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-medium ${postureClass(row.action_posture)}`}>
                                                                {row.action_posture}
                                                            </span>
                                                        </td>
                                                        <td className="px-4 py-4">
                                                            <button
                                                                type="button"
                                                                className="min-h-11 rounded-full border border-[#cab89f] bg-white px-4 py-2 text-sm font-medium text-slate-700 transition hover:bg-[#f5efe4] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#8d6f44] focus-visible:ring-offset-2"
                                                                aria-expanded={expanded}
                                                                aria-controls={`${row.row_id}-detail`}
                                                                aria-label={`${expanded ? "Hide" : "View"} detail for ${row.person_name}`}
                                                                onClick={() => toggleExpanded(row.row_id)}
                                                            >
                                                                {expanded ? "Hide detail" : "View detail"}
                                                            </button>
                                                        </td>
                                                    </tr>
                                                    {expanded ? (
                                                        <tr className="border-t border-[#ebdfd1] bg-[#fcfaf6]">
                                                            <td colSpan={data.table_columns.length} className="px-4 py-4">
                                                                <div
                                                                    id={`${row.row_id}-detail`}
                                                                    className="grid gap-4 rounded-[20px] border border-[#dfd4c2] bg-white px-4 py-4 shadow-sm md:grid-cols-2"
                                                                >
                                                                    <DetailBlock label="Evidence" value={detail.evidence_quote} />
                                                                    <DetailBlock label="Source" value={detail.source_title || detail.source_url} link={detail.source_url} />
                                                                    {detail.source_marker ? (
                                                                        <DetailBlock label="Source marker" value={detail.source_marker} />
                                                                    ) : null}
                                                                    <DetailBlock label="Relationship leverage" value={renderLeverage(detail)} />
                                                                    <DetailBlock label="Credential proof" value={renderCredentialSummary(detail)} />
                                                                    {detail.person_detail && Object.keys(detail.person_detail).length ? (
                                                                        <DetailBlock label="Person detail" value={renderPersonDetail(detail.person_detail)} />
                                                                    ) : null}
                                                                </div>
                                                            </td>
                                                        </tr>
                                                    ) : null}
                                                </React.Fragment>
                                            );
                                        })}
                                    </tbody>
                                </table>
                            </div>
                        </div>

                        <div className="grid gap-3 md:hidden">
                            {rows.map((row) => {
                                const detail = detailsById[row.row_id] || {};
                                const expanded = expandedRowId === row.row_id;
                                return (
                                    <article key={row.row_id} className="rounded-[22px] border border-[#dccfbf] bg-white p-4 shadow-sm">
                                        <div className="flex items-start justify-between gap-3">
                                            <div>
                                                <span className={`inline-flex rounded-full border px-2.5 py-1 text-[0.72rem] font-semibold uppercase tracking-[0.18em] ${badgeClass(row.signal)}`}>
                                                    {row.signal}
                                                </span>
                                                <h3 className="mt-3 font-medium text-slate-900">{row.person_name}</h3>
                                                <p className="mt-1 text-sm text-slate-600">{row.new_role}</p>
                                            </div>
                                            <button
                                                type="button"
                                                className="min-h-11 rounded-full border border-[#cab89f] bg-white px-4 py-2 text-sm font-medium text-slate-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#8d6f44] focus-visible:ring-offset-2"
                                                aria-expanded={expanded}
                                                aria-controls={`${row.row_id}-mobile-detail`}
                                                aria-label={`${expanded ? "Hide" : "View"} detail for ${row.person_name}`}
                                                onClick={() => toggleExpanded(row.row_id)}
                                            >
                                                {expanded ? "Hide" : "Detail"}
                                            </button>
                                        </div>

                                        <dl className="mt-4 grid grid-cols-2 gap-3 text-sm">
                                            <Definition label="Known" value={row.known ? "Yes" : "No"} />
                                            <Definition label="Worked With" value={row.worked_with ? "Yes" : "No"} />
                                            <Definition label="Projects" value={row.project_count} />
                                            <Definition label="Wins" value={row.win_count} />
                                        </dl>

                                        {expanded ? (
                                            <div id={`${row.row_id}-mobile-detail`} className="mt-4 grid gap-3 rounded-[18px] border border-[#dfd4c2] bg-[#faf7f1] p-4">
                                                <DetailBlock label="Previous role" value={row.previous_role} compact />
                                                <DetailBlock label="Movement type" value={row.movement_type} compact />
                                                <DetailBlock label="Why now" value={detail.evidence_quote} compact />
                                                <DetailBlock label="Source" value={detail.source_title || detail.source_url} link={detail.source_url} compact />
                                                {detail.source_marker ? (
                                                    <DetailBlock label="Source marker" value={detail.source_marker} compact />
                                                ) : null}
                                                <DetailBlock label="Leverage" value={renderLeverage(detail)} compact />
                                                <DetailBlock label="Credential proof" value={renderCredentialSummary(detail)} compact />
                                                {detail.person_detail && Object.keys(detail.person_detail).length ? (
                                                    <DetailBlock label="Person detail" value={renderPersonDetail(detail.person_detail)} compact />
                                                ) : null}
                                            </div>
                                        ) : null}
                                    </article>
                                );
                            })}
                        </div>
                    </SectionCard>

                    <SectionCard title="Where to Act">
                        <ol className="grid gap-3">
                            {actions.map((action, index) => (
                                <li
                                    key={`${action.person_name}-${index}`}
                                    className="rounded-[20px] border border-[#dccfbf] bg-white px-4 py-4 shadow-sm"
                                >
                                    <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                                        <div className="space-y-2">
                                            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-[#6f5a42]">
                                                {index + 1}
                                            </p>
                                            <h3 className="text-lg font-medium tracking-[-0.02em] text-slate-900">
                                                {action.person_name}
                                            </h3>
                                            <span className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-medium ${postureClass(action.action_posture)}`}>
                                                {action.action_posture}
                                            </span>
                                        </div>
                                        {action.relationship_owner ? (
                                            <p className="text-sm text-slate-600">
                                                Move first: <span className="font-medium text-slate-800">{action.relationship_owner}</span>
                                            </p>
                                        ) : null}
                                    </div>
                                    <p className="mt-3 text-sm leading-6 text-slate-700">{action.likely_play}</p>
                                    <p className="mt-2 text-sm leading-6 text-slate-600">{action.why_now}</p>
                                </li>
                            ))}
                        </ol>
                    </SectionCard>

                    <SectionCard title="Takeaway">
                        <p className="text-sm leading-7 text-slate-700">{data.takeaway || "No takeaway available."}</p>
                    </SectionCard>
                </main>
            </div>
        </section>
    );
}

function SectionCard({ title, children }) {
    return (
        <section className="rounded-[24px] border border-[#e2d7c5] bg-white/80 px-4 py-4 shadow-sm backdrop-blur sm:px-6">
            <h2 className="text-[0.72rem] font-semibold uppercase tracking-[0.3em] text-[#6f5a42]">
                {title}
            </h2>
            <div className="mt-4">{children}</div>
        </section>
    );
}

function StatCard({ label, value }) {
    return (
        <div className="rounded-[20px] border border-[#e3d7c5] bg-[#fcfaf7] px-4 py-3">
            <p className="text-[0.68rem] font-semibold uppercase tracking-[0.26em] text-[#6f5a42]">{label}</p>
            <p className="mt-2 text-2xl font-semibold tracking-[-0.04em] text-slate-900">{value}</p>
        </div>
    );
}

function Definition({ label, value }) {
    return (
        <div className="rounded-2xl border border-[#e5d9c7] bg-[#fcfaf7] px-3 py-3">
            <dt className="text-[0.68rem] font-semibold uppercase tracking-[0.2em] text-[#6f5a42]">{label}</dt>
            <dd className="mt-2 text-sm text-slate-800">{value}</dd>
        </div>
    );
}

function DetailBlock({ label, value, link = "", compact = false }) {
    return (
        <div className={compact ? "space-y-1" : "space-y-2"}>
            <p className="text-[0.68rem] font-semibold uppercase tracking-[0.22em] text-[#6f5a42]">
                {label}
            </p>
            {link ? (
                <a className="break-words text-sm leading-6 text-slate-800 underline decoration-[#a88a63] decoration-1 underline-offset-2" href={link} target="_blank" rel="noreferrer">
                    {value}
                </a>
            ) : (
                <p className="text-sm leading-6 text-slate-800 whitespace-pre-line">{value || "—"}</p>
            )}
        </div>
    );
}

function renderLeverage(detail) {
    const pieces = [];
    if (detail.known !== undefined) {
        pieces.push(`Known: ${detail.known ? "Yes" : "No"}`);
    }
    if (detail.worked_with !== undefined) {
        pieces.push(`Worked with: ${detail.worked_with ? "Yes" : "No"}`);
    }
    if (detail.project_count !== undefined || detail.win_count !== undefined) {
        pieces.push(`Projects: ${detail.project_count || 0} | Wins: ${detail.win_count || 0}`);
    }
    if (detail.relationship_owner) {
        pieces.push(`Relationship owner: ${detail.relationship_owner}`);
    }
    if (detail.person_match_status) {
        pieces.push(`Match: ${detail.person_match_status}`);
    }
    return pieces.join("\n");
}

function renderCredentialSummary(detail) {
    const pieces = [];
    if (detail.lookup_status) {
        pieces.push(`Lookup: ${detail.lookup_status}`);
    }
    if (detail.credential_summary) {
        pieces.push(detail.credential_summary);
    }
    if (Array.isArray(detail.matched_credentials) && detail.matched_credentials.length) {
        pieces.push(
            detail.matched_credentials
                .slice(0, 2)
                .map((cred) => `${cred.title} (${cred.url})`)
                .join("\n")
        );
    }
    return pieces.join("\n");
}

function renderPersonDetail(personDetail) {
    const pieces = [];
    if (personDetail.name) pieces.push(`Name: ${personDetail.name}`);
    if (personDetail.title) pieces.push(`Title: ${personDetail.title}`);
    if (personDetail.location) pieces.push(`Location: ${personDetail.location}`);
    if (personDetail.linkedin_url) pieces.push(`LinkedIn: ${personDetail.linkedin_url}`);
    return pieces.join("\n");
}
