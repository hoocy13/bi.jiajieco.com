export function finalistTeamIds(t) {
  if (t?.finalist_team_ids?.length) return t.finalist_team_ids
  if (!t?.qualification_slots?.length) return []
  const matches=t.matches||[], byId=Object.fromEntries(matches.map(m=>[m.id,m]))
  const direct=matches.filter(m=>m.stage==='second'&&!t.qualification_slots.includes(m.id)).map(m=>m.winner)
  return t.qualification_mode==='four-paired' ? [...direct,byId.C1?.winner,byId.C2?.winner,null] : [byId.C1?.winner,...direct]
}

export function hasSemifinalDraw(t) {
  return !!t?.semi_pairing_drawn || (t?.matches||[]).some(m=>m.stage==='semi'&&(m.score_a||m.score_b||m.winner))
}
export function semifinalTeamId(t,index) {
  return hasSemifinalDraw(t) ? finalistTeamIds(t)[index] : null
}
