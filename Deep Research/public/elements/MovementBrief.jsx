import React, { useState } from "react";

const BRIEF_STYLES = `
  .movement-brief {
    width: 100%;
    max-width: min(94rem, 100%);
    margin: 0 auto;
    padding: 0 clamp(0.25rem, 1vw, 0.75rem);
    min-width: 0;
    color: #1f2937;
    font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif;
  }

  .movement-brief,
  .movement-brief * {
    box-sizing: border-box;
  }

  .movement-brief__surface {
    width: 100%;
    max-width: 100%;
    background: #f7f4ee;
    border: 1px solid #d9d2c6;
    border-radius: 1.5rem;
    box-shadow: 0 18px 48px rgba(15, 23, 42, 0.08);
    padding: clamp(1rem, 2vw, 1.75rem);
    overflow: clip;
  }

  .movement-brief__header,
  .movement-brief__section {
    background: #ffffff;
    border: 1px solid #e5ddd1;
    border-radius: 1.25rem;
  }

  .movement-brief__header {
    padding: clamp(1rem, 2vw, 1.5rem);
  }

  .movement-brief__header-layout {
    display: grid;
    grid-template-columns: minmax(0, 1.6fr) minmax(18rem, 1fr);
    gap: 1rem;
    align-items: start;
  }

  .movement-brief__kicker,
  .movement-brief__section-title,
  .movement-brief__stat-label,
  .movement-brief__definition-label,
  .movement-brief__detail-label,
  .movement-brief__action-index {
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 0.18em;
    text-transform: uppercase;
    color: #7a5a2e;
  }

  .movement-brief__title {
    margin: 0.5rem 0 0 0;
    color: #12263a;
    font-family: "Iowan Old Style", "Georgia", serif;
    font-size: clamp(2rem, 3vw, 2.8rem);
    line-height: 1.05;
    letter-spacing: -0.04em;
  }

  .movement-brief__subtitle {
    margin: 0.75rem 0 0 0;
    max-width: 44rem;
    color: #475569;
    font-size: 0.98rem;
    line-height: 1.65;
  }

  .movement-brief__stat-grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 0.875rem;
  }

  .movement-brief__stat-card {
    border: 1px solid #e7dfd2;
    border-radius: 1rem;
    background: #fcfaf6;
    padding: 1rem;
  }

  .movement-brief__stat-value {
    margin-top: 0.5rem;
    color: #12263a;
    font-size: 2rem;
    font-weight: 700;
    letter-spacing: -0.04em;
  }

  .movement-brief__body {
    margin-top: 1rem;
    display: grid;
    gap: 1rem;
  }

  .movement-brief__section {
    padding: clamp(1rem, 2vw, 1.4rem);
  }

  .movement-brief__move-grid {
    display: grid;
    grid-template-columns: minmax(0, 1.5fr) minmax(16rem, 0.95fr);
    gap: 1rem;
    align-items: start;
  }

  .movement-brief__lead {
    margin: 0;
    color: #24364a;
    font-size: 1rem;
    line-height: 1.75;
    white-space: pre-line;
  }

  .movement-brief__definition-grid {
    display: grid;
    gap: 0.75rem;
  }

  .movement-brief__definition {
    border: 1px solid #e7dfd2;
    border-radius: 1rem;
    background: #fcfaf6;
    padding: 0.9rem 1rem;
  }

  .movement-brief__definition-value {
    margin: 0.55rem 0 0 0;
    color: #24364a;
    font-size: 0.95rem;
    line-height: 1.5;
    word-break: break-word;
  }

  .movement-brief__signal-list,
  .movement-brief__context-list,
  .movement-brief__action-list {
    display: grid;
    gap: 0.75rem;
    margin: 0;
    padding: 0;
    list-style: none;
  }

  .movement-brief__signal-list {
    grid-template-columns: repeat(auto-fit, minmax(15rem, 1fr));
  }

  .movement-brief__signal-item,
  .movement-brief__context-item,
  .movement-brief__action-item,
  .movement-brief__mobile-row,
  .movement-brief__detail-grid {
    border: 1px solid #e7dfd2;
    border-radius: 1rem;
    background: #fcfaf7;
  }

  .movement-brief__signal-item,
  .movement-brief__context-item,
  .movement-brief__action-item,
  .movement-brief__mobile-row {
    padding: 1rem;
  }

  .movement-brief__signal-item {
    color: #334155;
    font-size: 0.96rem;
    line-height: 1.65;
  }

  .movement-brief__context-header,
  .movement-brief__action-header {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 0.75rem;
  }

  .movement-brief__context-title,
  .movement-brief__action-title,
  .movement-brief__mobile-row-title {
    margin: 0;
    color: #12263a;
    font-size: 1.05rem;
    font-weight: 700;
    line-height: 1.35;
    letter-spacing: -0.02em;
  }

  .movement-brief__context-rationale,
  .movement-brief__action-copy,
  .movement-brief__action-why,
  .movement-brief__detail-value,
  .movement-brief__mobile-row-subtitle,
  .movement-brief__takeaway {
    color: #334155;
    font-size: 0.95rem;
    line-height: 1.7;
  }

  .movement-brief__context-rationale,
  .movement-brief__action-copy,
  .movement-brief__action-why,
  .movement-brief__takeaway {
    margin: 0.75rem 0 0 0;
  }

  .movement-brief__table-shell {
    overflow-x: auto;
    border: 1px solid #e2d8ca;
    border-radius: 1rem;
    background: #ffffff;
  }

  .movement-brief__table {
    width: 100%;
    min-width: 72rem;
    border-collapse: collapse;
    text-align: left;
  }

  .movement-brief__table thead {
    background: #f6efe2;
  }

  .movement-brief__table th,
  .movement-brief__table td {
    padding: 0.95rem 1rem;
    vertical-align: top;
    border-top: 1px solid #ece3d7;
  }

  .movement-brief__table thead th {
    border-top: none;
    color: #7a5a2e;
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    white-space: nowrap;
  }

  .movement-brief__table tbody th {
    color: #12263a;
    font-size: 0.95rem;
    font-weight: 700;
  }

  .movement-brief__table-row--featured td,
  .movement-brief__table-row--featured th {
    background: linear-gradient(90deg, rgba(245, 238, 226, 0.98), rgba(255, 250, 241, 0.98));
  }

  .movement-brief__table-row--featured td:first-child,
  .movement-brief__table-row--featured th:first-of-type {
    box-shadow: inset 0.3rem 0 0 #c78f2d;
  }

  .movement-brief__person-cell {
    display: grid;
    gap: 0.45rem;
  }

  .movement-brief__focus-chip {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: fit-content;
    border-radius: 999px;
    border: 1px solid #d8b15f;
    background: #fff3d6;
    color: #8a5a11;
    padding: 0.22rem 0.65rem;
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
  }

  .movement-brief__table-cell {
    color: #334155;
    font-size: 0.92rem;
    line-height: 1.55;
  }

  .movement-brief__badge,
  .movement-brief__posture,
  .movement-brief__confidence {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    border-radius: 999px;
    padding: 0.3rem 0.7rem;
    font-size: 0.76rem;
    font-weight: 700;
    line-height: 1.1;
  }

  .movement-brief__badge {
    text-transform: uppercase;
    letter-spacing: 0.12em;
    border: 1px solid transparent;
  }

  .movement-brief__badge--buyer {
    background: #f3ead8;
    border-color: #d6c09c;
    color: #5f4a21;
  }

  .movement-brief__badge--exec {
    background: #e7eef8;
    border-color: #bfd0ec;
    color: #224166;
  }

  .movement-brief__posture {
    border: 1px solid transparent;
  }

  .movement-brief__posture--immediate {
    background: #dcfce7;
    border-color: #86efac;
    color: #166534;
  }

  .movement-brief__posture--expansion {
    background: #fef3c7;
    border-color: #fcd34d;
    color: #92400e;
  }

  .movement-brief__posture--monitor {
    background: #e2e8f0;
    border-color: #cbd5e1;
    color: #334155;
  }

  .movement-brief__confidence {
    background: #fef3c7;
    border: 1px solid #fcd34d;
    color: #92400e;
    white-space: nowrap;
  }

  .movement-brief__detail-button {
    min-height: 2.75rem;
    border: 1px solid #ccb99c;
    border-radius: 999px;
    background: #ffffff;
    color: #24364a;
    padding: 0.6rem 0.95rem;
    font-size: 0.9rem;
    font-weight: 700;
    cursor: pointer;
  }

  .movement-brief__detail-button:hover {
    background: #f5eee2;
  }

  .movement-brief__detail-grid {
    padding: 1rem;
    display: grid;
    gap: 0.9rem;
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .movement-brief__detail-label {
    margin: 0;
  }

  .movement-brief__detail-value {
    margin: 0.45rem 0 0 0;
    white-space: pre-line;
    word-break: break-word;
  }

  .movement-brief__link {
    color: #0f4c81;
    text-decoration: underline;
    text-underline-offset: 0.15rem;
    word-break: break-word;
  }

  .movement-brief__mobile-list {
    display: none;
  }

  .movement-brief__mobile-row-top {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 0.75rem;
  }

  .movement-brief__mobile-row-subtitle {
    margin: 0.5rem 0 0 0;
  }

  .movement-brief__mobile-row--featured {
    border-color: #d8b15f;
    box-shadow: inset 0.28rem 0 0 #c78f2d;
    background: linear-gradient(90deg, rgba(245, 238, 226, 0.98), rgba(255, 250, 241, 0.98));
  }

  .movement-brief__mobile-metrics {
    margin-top: 0.9rem;
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 0.65rem;
  }

  .movement-brief__empty {
    color: #475569;
    font-size: 0.95rem;
    line-height: 1.6;
    margin: 0;
  }

  .movement-brief__footer-actions {
    display: flex;
    flex-wrap: wrap;
    gap: 0.75rem;
  }

  .movement-brief__footer-button {
    min-height: 2.9rem;
    border: 1px solid #ccb99c;
    border-radius: 999px;
    background: #ffffff;
    color: #24364a;
    padding: 0.7rem 1rem;
    font-size: 0.92rem;
    font-weight: 700;
    cursor: pointer;
  }

  .movement-brief__footer-button:hover:not(:disabled) {
    background: #f5eee2;
  }

  .movement-brief__footer-button:disabled {
    opacity: 0.65;
    cursor: wait;
  }

  .movement-brief__footer-error {
    margin: 0.85rem 0 0 0;
    color: #b42318;
    font-size: 0.92rem;
    line-height: 1.5;
  }

  @media (max-width: 960px) {
    .movement-brief__header-layout,
    .movement-brief__move-grid,
    .movement-brief__detail-grid {
      grid-template-columns: 1fr;
    }

    .movement-brief__desktop-table {
      display: none;
    }

    .movement-brief__mobile-list {
      display: grid;
      gap: 0.75rem;
    }
  }
`;

function safeList(value) {
    return Array.isArray(value) ? value : [];
}

function badgeVariant(signal) {
    return signal === "BUYER"
        ? "movement-brief__badge movement-brief__badge--buyer"
        : "movement-brief__badge movement-brief__badge--exec";
}

function postureVariant(posture) {
    if (posture === "Immediate Re-engagement") {
        return "movement-brief__posture movement-brief__posture--immediate";
    }
    if (posture === "Expansion Opportunity") {
        return "movement-brief__posture movement-brief__posture--expansion";
    }
    return "movement-brief__posture movement-brief__posture--monitor";
}

export default function MovementBrief() {
    const [expandedRowId, setExpandedRowId] = useState(null);
    const [pendingActionKey, setPendingActionKey] = useState("");
    const [actionError, setActionError] = useState("");
    const data = typeof props === "object" && props ? props : {};
    const rows = safeList(data.movement_rows);
    const detailsById = data.row_details_by_id || {};
    const actions = safeList(data.where_to_act);
    const stats = data.stats || {};
    const moveSummary = data.move_summary || {};
    const signalSummary = safeList(data.signal_summary);
    const destinationOpportunityContext = safeList(data.destination_account_opportunity_context);
    const footerActions = safeList(data.footer_actions);

    const toggleExpanded = (rowId) => {
        setExpandedRowId((current) => (current === rowId ? null : rowId));
    };

    const invokeFooterAction = async (action) => {
        if (!action || !action.name || typeof callAction !== "function") {
            return;
        }
        const key = actionKey(action);
        setPendingActionKey(key);
        setActionError("");
        try {
            await callAction({
                name: action.name,
                payload: action.payload || {},
            });
        } catch (error) {
            console.error("Movement brief footer action failed", error);
            setActionError("Action failed. Check the terminal logs and try again.");
        } finally {
            setPendingActionKey("");
        }
    };

    return (
        <section className="movement-brief">
            <style>{BRIEF_STYLES}</style>
            <div className="movement-brief__surface">
                <header className="movement-brief__header">
                    <div className="movement-brief__header-layout">
                        <div>
                            <div className="movement-brief__kicker">People Movement Brief</div>
                            <h1 className="movement-brief__title">{data.title || "People Movement Brief"}</h1>
                            <p className="movement-brief__subtitle">
                                {data.subtitle || "Executive and buyer movement with leverage, proof, and next actions."}
                            </p>
                        </div>
                        <div className="movement-brief__stat-grid">
                            <StatCard label="Movers" value={stats.visible_rows ?? rows.length} />
                            <StatCard label="EXEC" value={stats.exec_rows ?? 0} />
                            <StatCard label="BUYER" value={stats.buyer_rows ?? 0} />
                            <StatCard label="Actions" value={stats.actions ?? actions.length} />
                        </div>
                    </div>
                </header>

                <main className="movement-brief__body">
                    <SectionCard title="Move Summary">
                        <div className="movement-brief__move-grid">
                            <p className="movement-brief__lead">
                                {moveSummary.summary_text || "No move summary available."}
                            </p>
                            <div className="movement-brief__definition-grid">
                                <Definition label="Person" value={moveSummary.person_name || "—"} />
                                <Definition
                                    label="Move"
                                    value={`${moveSummary.from_company || "—"} -> ${moveSummary.to_company || "—"}`}
                                />
                                <Definition label="Target Role" value={moveSummary.new_role || "—"} />
                                <Definition label="Lookback" value={`${moveSummary.lookback_days || 180} days`} />
                                <Definition label="Scenario" value={moveSummary.synthetic_scenario ? "Synthetic" : "Live"} />
                                <Definition label="Warm Path" value={moveSummary.warm_intro_path_available ? "Yes" : "No"} />
                            </div>
                        </div>
                    </SectionCard>

                    <SectionCard title="Signal Summary">
                        {signalSummary.length ? (
                            <div className="movement-brief__signal-list">
                                {signalSummary.map((item, index) => (
                                    <div key={`${index}-${item}`} className="movement-brief__signal-item">
                                        {item}
                                    </div>
                                ))}
                            </div>
                        ) : (
                            <p className="movement-brief__empty">No signal summary available.</p>
                        )}
                    </SectionCard>

                    {destinationOpportunityContext.length ? (
                        <SectionCard title="Destination Account Opportunity Context">
                            <div className="movement-brief__context-list">
                                {destinationOpportunityContext.map((item, index) => (
                                    <article key={`${item.title}-${index}`} className="movement-brief__context-item">
                                        <div className="movement-brief__context-header">
                                            <div>
                                                <h3 className="movement-brief__context-title">{item.title}</h3>
                                                <p className="movement-brief__context-rationale">
                                                    {item.rationale || "No supporting rationale available."}
                                                </p>
                                            </div>
                                            <span className="movement-brief__confidence">{item.confidence || "Medium"}</span>
                                        </div>
                                    </article>
                                ))}
                            </div>
                        </SectionCard>
                    ) : null}

                    <SectionCard title="Who Has Moved - And Where We Have Leverage">
                        {rows.length ? (
                            <>
                                <div className="movement-brief__desktop-table">
                                    <div className="movement-brief__table-shell">
                                        <table className="movement-brief__table">
                                            <caption style={{ display: "none" }}>
                                                Executive and buyer movement table with inline leverage and proof details.
                                            </caption>
                                            <thead>
                                                <tr>
                                                    {(data.table_columns || []).map((column) => (
                                                        <th key={column} scope="col">
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
                                                            <tr className={row.is_focus_move ? "movement-brief__table-row--featured" : undefined}>
                                                                <td>
                                                                    <span className={badgeVariant(row.signal)}>{row.signal}</span>
                                                                </td>
                                                                <th scope="row">
                                                                    <div className="movement-brief__person-cell">
                                                                        <span>{row.person_name}</span>
                                                                        {row.is_focus_move ? (
                                                                            <span className="movement-brief__focus-chip">Focus move</span>
                                                                        ) : null}
                                                                    </div>
                                                                </th>
                                                                <td className="movement-brief__table-cell">{row.previous_role}</td>
                                                                <td className="movement-brief__table-cell">{row.new_role}</td>
                                                                <td className="movement-brief__table-cell">{row.movement_type}</td>
                                                                <td className="movement-brief__table-cell">{row.known ? "Yes" : "No"}</td>
                                                                <td className="movement-brief__table-cell">{row.worked_with ? "Yes" : "No"}</td>
                                                                <td className="movement-brief__table-cell">{row.project_count}</td>
                                                                <td className="movement-brief__table-cell">{row.win_count}</td>
                                                                <td className="movement-brief__table-cell">{row.relationship_owner || "—"}</td>
                                                                <td>
                                                                    <span className={postureVariant(row.action_posture)}>{row.action_posture}</span>
                                                                </td>
                                                                <td>
                                                                    <button
                                                                        type="button"
                                                                        className="movement-brief__detail-button"
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
                                                                <tr>
                                                                    <td colSpan={(data.table_columns || []).length || 12}>
                                                                        <div id={`${row.row_id}-detail`} className="movement-brief__detail-grid">
                                                                            <DetailBlock label="Evidence" value={detail.evidence_quote} />
                                                                            <DetailBlock
                                                                                label="Source"
                                                                                value={detail.source_title || detail.source_url}
                                                                                link={detail.source_url}
                                                                            />
                                                                            {Array.isArray(detail.internal_connections) && detail.internal_connections.length ? (
                                                                                <DetailBlock label="Internal connections" value={renderInternalConnections(detail)} />
                                                                            ) : null}
                                                                            <DetailBlock label="Relationship leverage" value={renderLeverage(detail)} />
                                                                            <DetailBlock label="Credential proof" value={renderCredentialSummary(detail)} />
                                                                            {detail.person_detail && Object.keys(detail.person_detail).length ? (
                                                                                <DetailBlock
                                                                                    label="Person detail"
                                                                                    value={renderPersonDetail(detail.person_detail)}
                                                                                />
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

                                <div className="movement-brief__mobile-list">
                                    {rows.map((row) => {
                                        const detail = detailsById[row.row_id] || {};
                                        const expanded = expandedRowId === row.row_id;
                                        return (
                                            <article
                                                key={row.row_id}
                                                className={`movement-brief__mobile-row${row.is_focus_move ? " movement-brief__mobile-row--featured" : ""}`}
                                            >
                                                <div className="movement-brief__mobile-row-top">
                                                    <div>
                                                        <span className={badgeVariant(row.signal)}>{row.signal}</span>
                                                        <h3 className="movement-brief__mobile-row-title">{row.person_name}</h3>
                                                        {row.is_focus_move ? (
                                                            <div style={{ marginTop: "0.45rem" }}>
                                                                <span className="movement-brief__focus-chip">Focus move</span>
                                                            </div>
                                                        ) : null}
                                                        <p className="movement-brief__mobile-row-subtitle">{row.new_role}</p>
                                                    </div>
                                                    <button
                                                        type="button"
                                                        className="movement-brief__detail-button"
                                                        aria-expanded={expanded}
                                                        aria-controls={`${row.row_id}-mobile-detail`}
                                                        aria-label={`${expanded ? "Hide" : "View"} detail for ${row.person_name}`}
                                                        onClick={() => toggleExpanded(row.row_id)}
                                                    >
                                                        {expanded ? "Hide" : "Detail"}
                                                    </button>
                                                </div>

                                                <div className="movement-brief__mobile-metrics">
                                                    <Definition label="Known" value={row.known ? "Yes" : "No"} />
                                                    <Definition label="Worked With" value={row.worked_with ? "Yes" : "No"} />
                                                    <Definition label="Current Projects" value={row.project_count} />
                                                    <Definition label="Wins" value={row.win_count} />
                                                </div>

                                                {expanded ? (
                                                    <div id={`${row.row_id}-mobile-detail`} className="movement-brief__detail-grid" style={{ marginTop: "0.9rem" }}>
                                                        <DetailBlock label="Previous role" value={row.previous_role} compact />
                                                        <DetailBlock label="Movement type" value={row.movement_type} compact />
                                                        <DetailBlock label="Why now" value={detail.evidence_quote} compact />
                                                        <DetailBlock
                                                            label="Source"
                                                            value={detail.source_title || detail.source_url}
                                                            link={detail.source_url}
                                                            compact
                                                        />
                                                        {Array.isArray(detail.internal_connections) && detail.internal_connections.length ? (
                                                            <DetailBlock label="Internal connections" value={renderInternalConnections(detail)} compact />
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
                            </>
                        ) : (
                            <p className="movement-brief__empty">No movement rows were retained for the cover brief.</p>
                        )}
                    </SectionCard>

                    <SectionCard title="Where to Act">
                        {actions.length ? (
                            <ol className="movement-brief__action-list">
                                {actions.map((action, index) => (
                                    <li key={`${action.person_name}-${index}`} className="movement-brief__action-item">
                                        <div className="movement-brief__action-header">
                                            <div>
                                                <div className="movement-brief__action-index">{index + 1}</div>
                                                <h3 className="movement-brief__action-title">{action.person_name}</h3>
                                                <div style={{ marginTop: "0.6rem" }}>
                                                    <span className={postureVariant(action.action_posture)}>{action.action_posture}</span>
                                                </div>
                                            </div>
                                            {action.relationship_owner ? (
                                                <div className="movement-brief__action-copy" style={{ marginTop: 0 }}>
                                                    Move first: <strong style={{ color: "#12263a" }}>{action.relationship_owner}</strong>
                                                </div>
                                            ) : null}
                                        </div>
                                        <p className="movement-brief__action-copy">{action.likely_play}</p>
                                        <p className="movement-brief__action-why">{action.why_now}</p>
                                    </li>
                                ))}
                            </ol>
                        ) : (
                            <p className="movement-brief__empty">No prioritized actions were available.</p>
                        )}
                    </SectionCard>

                    <SectionCard title="Takeaway">
                        <p className="movement-brief__takeaway">{data.takeaway || "No takeaway available."}</p>
                    </SectionCard>

                    {footerActions.length ? (
                        <SectionCard title="Open Supporting Movement Artifacts Or Launch Another Movement Scan">
                            <div className="movement-brief__footer-actions">
                                {footerActions.map((action) => {
                                    const key = actionKey(action);
                                    const disabled = typeof callAction !== "function" || pendingActionKey === key;
                                    return (
                                        <button
                                            key={key}
                                            type="button"
                                            className="movement-brief__footer-button"
                                            disabled={disabled}
                                            onClick={() => invokeFooterAction(action)}
                                        >
                                            {pendingActionKey === key ? "Opening..." : action.label}
                                        </button>
                                    );
                                })}
                            </div>
                            {actionError ? <p className="movement-brief__footer-error">{actionError}</p> : null}
                        </SectionCard>
                    ) : null}
                </main>
            </div>
        </section>
    );
}

function SectionCard({ title, children }) {
    return (
        <section className="movement-brief__section">
            <div className="movement-brief__section-title">{title}</div>
            <div style={{ marginTop: "1rem" }}>{children}</div>
        </section>
    );
}

function StatCard({ label, value }) {
    return (
        <div className="movement-brief__stat-card">
            <div className="movement-brief__stat-label">{label}</div>
            <div className="movement-brief__stat-value">{value}</div>
        </div>
    );
}

function Definition({ label, value }) {
    return (
        <div className="movement-brief__definition">
            <div className="movement-brief__definition-label">{label}</div>
            <div className="movement-brief__definition-value">{value}</div>
        </div>
    );
}

function DetailBlock({ label, value, link = "", compact = false }) {
    const isPrimitiveValue = typeof value === "string" || typeof value === "number";
    return (
        <div style={{ minWidth: 0 }}>
            <div className="movement-brief__detail-label">{label}</div>
            {link ? (
                <a
                    className="movement-brief__link"
                    href={link}
                    target="_blank"
                    rel="noreferrer"
                    style={{ display: "inline-block", marginTop: compact ? "0.35rem" : "0.45rem" }}
                >
                    {value}
                </a>
            ) : (
                isPrimitiveValue ? (
                    <p className="movement-brief__detail-value" style={{ marginTop: compact ? "0.35rem" : "0.45rem" }}>
                        {value || "—"}
                    </p>
                ) : (
                    <div className="movement-brief__detail-value" style={{ marginTop: compact ? "0.35rem" : "0.45rem" }}>
                        {value || "—"}
                    </div>
                )
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
        pieces.push(`Current Projects: ${detail.project_count || 0} | Wins: ${detail.win_count || 0}`);
    }
    if (detail.relationship_owner) {
        pieces.push(`Relationship owner: ${detail.relationship_owner}`);
    }
    if (detail.person_match_status) {
        pieces.push(`Match: ${detail.person_match_status}`);
    }
    return pieces.join("\n");
}

function renderInternalConnections(detail) {
    const connections = Array.isArray(detail.internal_connections) ? detail.internal_connections.slice(0, 3) : [];
    if (!connections.length) {
        return "—";
    }
    return connections.join("\n");
}

function renderCredentialSummary(detail) {
    const matchedCredentials = Array.isArray(detail.matched_credentials) ? detail.matched_credentials.slice(0, 2) : [];
    const hasContent = detail.lookup_status || detail.credential_summary || matchedCredentials.length;
    if (!hasContent) {
        return "—";
    }

    return (
        <div style={{ display: "grid", gap: "0.55rem" }}>
            {detail.lookup_status ? <div>{`Lookup: ${detail.lookup_status}`}</div> : null}
            {detail.credential_summary ? <div>{detail.credential_summary}</div> : null}
            {matchedCredentials.length ? (
                <div style={{ display: "grid", gap: "0.55rem" }}>
                    {matchedCredentials.map((cred, index) => (
                        <div
                            key={`${cred.title || "credential"}-${index}`}
                            style={{
                                borderTop: index === 0 ? "none" : "1px solid rgba(15, 23, 42, 0.08)",
                                paddingTop: index === 0 ? 0 : "0.55rem",
                                display: "grid",
                                gap: "0.25rem",
                            }}
                        >
                            <div style={{ fontWeight: 600 }}>{cred.title}</div>
                            {cred.why_relevant ? <div>{`Why relevant: ${cred.why_relevant}`}</div> : null}
                            {cred.url ? (
                                <a
                                    className="movement-brief__link"
                                    href={cred.url}
                                    target="_blank"
                                    rel="noreferrer"
                                    style={{ width: "fit-content" }}
                                >
                                    View credential
                                </a>
                            ) : null}
                        </div>
                    ))}
                </div>
            ) : null}
        </div>
    );
}

function renderPersonDetail(personDetail) {
    const pieces = [];
    if (personDetail.name) pieces.push(`Name: ${personDetail.name}`);
    if (personDetail.title) pieces.push(`Title: ${personDetail.title}`);
    if (personDetail.location) pieces.push(`Location: ${personDetail.location}`);
    if (personDetail.linkedin_url) pieces.push(`LinkedIn: ${personDetail.linkedin_url}`);
    return pieces.join("\n");
}

function actionKey(action) {
    return `${action?.name || ""}:${JSON.stringify(action?.payload || {})}`;
}
