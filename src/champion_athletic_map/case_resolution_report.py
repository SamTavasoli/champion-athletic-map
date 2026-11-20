"""Render the private case proposals as a standalone team review page."""

from html import escape
import json


def text(value):
    return escape(str(value), quote=True)


def dump(value):
    return '<pre>' + text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)) + '</pre>'


def details(label, value):
    return '<details><summary>' + text(label) + '</summary>' + dump(value) + '</details>'


def render(profiles, metadata, activities, amendments, rules, families, food, register):
    activity_by_id = {r['profile_id']: r for r in activities['cases']}
    amendment_by_id = {r['profile_id']: r for r in amendments}
    rule_by_id = {r['profile_id']: r for r in rules['cases']}
    family_by_id = {r['profile_id']: r for r in families['all_case_family_proposals']}
    food_by_id = {r['profile_id']: r for r in food['cases']}
    register_by_id = {r['profile_id']: r for r in register}
    cards = []
    for index, record in enumerate(profiles, 1):
        pid, public = record['profile_id'], record['input']
        activity = activity_by_id.get(pid)
        change = amendment_by_id.get(pid)
        family = family_by_id[pid]
        rule = rule_by_id.get(pid)
        held = bool(activity and not activity.get('proposed_public_record') and not activity.get('private_witness'))
        pieces = [f'<article class="card" data-changed="{int(bool(change))}" data-held="{int(held)}" '
                  f'data-linked="{int(bool(family.get("current_development_pair_ids")))}">',
                  '<div class="eyebrow">Case ' + str(index) + ' · Age ' + text(public['age']) + ' · ' +
                  text(metadata[pid]['scenario_intent'].replace('_', ' ')) + '</div>',
                  '<h2>' + text('; '.join(public.get('goals') or ['Request review'])) + '</h2>',
                  '<p class="request">' + text(public['athlete_request']) + '</p>',
                  '<p class="small">' + text(pid) + '</p>']
        if activity:
            status = 'Current request held for a decision' if held else 'Source-linked activity proposal prepared'
            pieces.append('<p class="badge' + (' hold' if held else '') + '">' + status + '</p>')
            if change:
                pieces.append('<h3>Proposed fictional resource facts</h3><p>These are new authoring choices. '
                              'They are not facts recovered from the original case.</p>')
                pieces.append('<table><thead><tr><th>Field</th><th>Previous</th><th>Proposed</th></tr></thead><tbody>')
                for patch in change['public_field_changes']:
                    pieces.append('<tr><td>' + text(patch['field'].replace('/input/', '').replace('_', ' ')) +
                                  '</td><td>' + dump(patch['previous']) + '</td><td>' + dump(patch['proposed']) + '</td></tr>')
                pieces.append('</tbody></table>')
            elif not held:
                pieces.append('<p>The current resource facts are retained.</p>')
            witness = activity.get('private_witness')
            if witness:
                evidence = witness.get('source_evidence', {})
                if evidence:
                    pieces.append('<p><strong>Proposed source activity:</strong> ' +
                        text(evidence['drill_name']['value']) + ' · Source dose: ' +
                        text(evidence['source_prescription']['value']) + '</p>')
                    pieces.append('<p><strong>Skill review:</strong> Reported experience: ' +
                        text(public.get('basketball_background', {}).get('experience_level')) +
                        '; source curriculum level: ' + text(evidence.get('source_curriculum_level', {}).get('value')) +
                        '. These labels are not interchangeable. Review the source prerequisites and goal fit before accepting the witness.</p>')
                    pieces.append('<p>' + text(witness.get('goal_relation', '')) + '</p>')
                pieces.append(details('Activity, source prescription and private schedule example', witness))
            if held:
                pieces.append('<p>The current conditioning request remains held. The reviewed source does not '
                              'support a complete timed example for this request.</p>')
            optional = activity.get('optional_material_goal_reauthoring')
            if optional:
                pieces.append('<p><strong>Optional different request:</strong> A separately recorded goal change is available. '
                              'It has not been selected and is not included in the proposed case list.</p>')
                pieces.append(details('Optional goal change and its source evidence', optional))
            pieces.append(details('Full activity decision record', activity))
        else:
            pieces.append('<p class="badge">Challenge facts preserved</p><p>We retain the missing information, '
                          'conflict or scope boundary in this case.</p>')
        if rule:
            numeric = rule['numeric_rule_bounds']
            maximum = next(r for r in numeric if r['operator'] == '<=')
            rest = next(r for r in numeric if r['operator'] == '>=')
            pieces.append('<p><strong>Conditional weekly bounds:</strong> up to ' + text(maximum['bound_value']) +
                          ' basketball minutes against a ' + text(maximum['threshold']) + '-minute limit; at least ' +
                          text(rest['bound_value']) + ' basketball-free days. These calculations depend on accepting '
                          'the proposed complete schedule facts. Other-sport, game and camp qualifications still require contextual review. '
                          'They do not approve the activity or case.</p>')
            pieces.append(details('Applicable rules and remaining evidence', rule))
        pieces.append('<p><strong>Relationship proposal:</strong> ' + text(family['proposed_rationale']) + '</p>')
        if family.get('remaining_legacy_complete_source_comparison_count'):
            pieces.append('<p class="warning">The legacy-source comparison remains unresolved because its complete source facts are unavailable.</p>')
        pieces.append(details('Case-family proposal and retained links', family))
        if pid in food_by_id:
            pieces.append('<p><strong>Food question:</strong> The verified source answer and runtime wording are preserved.</p>')
            pieces.append(details('Private verified food expectation', food_by_id[pid]))
        pieces.append(details('Earlier schedule-completeness authoring proposal', register_by_id[pid]))
        pieces.append(details('Proposed public case — no private answer evidence', record))
        pieces.append('</article>')
        cards.append(''.join(pieces))
    a = activities['summary']
    overview = {
        'activity_proposals': a,
        'conditional_rule_bounds': rules['summary'],
        'case_relationship_proposals': families['summary'],
    }
    header = '''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Step 33-3 — Case decisions</title>
<style>
:root{color-scheme:light;font-family:system-ui,-apple-system,Segoe UI,sans-serif;color:#203142;background:#edf1f5}
body{margin:0}main{max-width:1160px;margin:auto;padding:32px 22px 60px}h1{font-size:2rem;margin:6px 0 12px}
h2{font-size:1.25rem;margin:7px 0}h3{font-size:1rem;margin-top:24px}p{line-height:1.55}
.lead{font-size:1.12rem;max-width:900px}.panel,.card{background:white;border:1px solid #cbd5df;border-radius:12px;padding:24px;margin:20px 0}
.toolbar{position:sticky;top:0;background:#edf1f5;padding:12px 0;z-index:1;display:flex;gap:10px;flex-wrap:wrap}
input,select{font:inherit;border:1px solid #9aa8b6;border-radius:7px;padding:10px}input{flex:1;min-width:220px}
.eyebrow,.small{color:#556778;font-size:.85rem}.request{border-left:3px solid #4c829c;padding-left:14px}
.badge{display:inline-block;background:#e4f1ed;color:#245a46;padding:6px 10px;border-radius:6px;font-size:.9rem}
.hold,.warning{background:#fff0d6;color:#784f04}.warning{padding:10px;border-radius:6px}
table{border-collapse:collapse;width:100%;table-layout:fixed}td,th{border:1px solid #d0d9e2;text-align:left;vertical-align:top;padding:10px}
th{background:#eef3f6}pre{white-space:pre-wrap;overflow-wrap:anywhere;font: .83rem/1.5 ui-monospace,Consolas,monospace;margin:7px 0}
details{margin:13px 0;border-top:1px solid #e1e6ed;padding-top:10px}summary{cursor:pointer;font-weight:600;color:#2c6078}
.count{font-weight:600}a{color:#175b8b}article[hidden]{display:none}@media(max-width:600px){main{padding:18px 12px}.card,.panel{padding:17px}td,th{padding:6px}}
</style></head><body><main><div class="eyebrow">Champions Athletic Map · Private evaluation preparation</div>
<h1>Step 33-3 — Case decisions</h1>
<p class="lead">We prepared specific activity and resource proposals for the remaining cases, checked the applicable weekly bounds, and documented the case relationships. The original cases and verified food answers are preserved.</p>
<section class="panel"><h2>What the team needs to decide</h2>
<p>Review the proposed fictional facts, the activity source and the private schedule example. Record a choice in <a href="working/team_decisions.csv">working/team_decisions.csv</a>. The optional conditioning alternatives change the goal and remain unselected.</p>
<p>Case-family suggestions document separate authored bases and shared design patterns. They do not prove statistical independence. The nine incomplete legacy comparisons remain open.</p>
<p>These are proposals. A case still needs recorded preparation, review by a distinct teammate, accepted evidence and the final protocol before a final planner run. The separate family sampling decision also remains to be agreed.</p>
<p>All evidence on this page is private review material. It must stay out of the planner prompts, retrieval inputs and internal evaluator.</p>
'''
    footer = '''<script>
const search=document.getElementById('search'),filter=document.getElementById('filter');
const cards=Array.from(document.querySelectorAll('article.card'));
function update(){let shown=0;const q=search.value.toLowerCase(),kind=filter.value;
for(const card of cards){const ok=(!q||card.textContent.toLowerCase().includes(q))&&(kind==='all'||card.dataset[kind]==='1');
card.hidden=!ok;if(ok)shown++;}document.getElementById('count').textContent=shown+' of '+cards.length+' cases';}
search.addEventListener('input',update);filter.addEventListener('change',update);update();
</script></main></body></html>'''
    return (header + details('Preparation counts and qualifications', overview) + '</section>' +
        '<div class="toolbar"><input id="search" aria-label="Search cases" placeholder="Search a goal, case ID or source">' +
        '<select id="filter" aria-label="Filter cases"><option value="all">All cases</option>' +
        '<option value="changed">New resource facts proposed</option><option value="held">Current request held</option>' +
        '<option value="linked">Current development links</option></select><span id="count" class="count"></span></div>' +
        ''.join(cards) + footer).encode('utf-8')
