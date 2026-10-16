export async function exportMonthlyReportPdf(root, filename) {
  if (!root) throw new Error('月报尚未完成渲染')
  const [{ jsPDF }, { default: html2canvas }] = await Promise.all([import('jspdf'), import('html2canvas')])
  await document.fonts?.ready
  await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))
  const roots = Array.isArray(root) ? root : [root]
  if (!roots.length) throw new Error('月报尚未完成渲染')
  const pdf = new jsPDF({ orientation: 'portrait', unit: 'pt', format: 'a4', compress: true })
  const margin = 22
  const width = pdf.internal.pageSize.getWidth() - margin * 2
  const height = pdf.internal.pageSize.getHeight() - margin * 2
  let pageCount = 0
  for (const pageRoot of roots) {
    const canvas = await html2canvas(pageRoot, { backgroundColor: '#ffffff', scale: 3, logging: false, useCORS: true, windowWidth: 794 })
    const scale = width / canvas.width
    const capacity = Math.floor(height / scale)
    const rootTop = pageRoot.getBoundingClientRect().top
    const ratio = canvas.height / pageRoot.getBoundingClientRect().height
    const bounds = element => {
      const rect = element.getBoundingClientRect()
      return { start: Math.floor((rect.top - rootTop) * ratio), end: Math.ceil((rect.bottom - rootTop) * ratio) }
    }
    const blocks = [...pageRoot.querySelectorAll('tr, .summary-metrics, svg, .mini-metrics')].map(bounds)
    for (const element of pageRoot.querySelectorAll('.summary-panel')) {
      const block = bounds(element)
      if (block.end - block.start < capacity * 0.8) blocks.push(block)
    }
    const header = pageRoot.querySelector('.channel-detail-table thead')
    const head = header ? bounds(header) : null
    let start = 0
    while (start < canvas.height) {
      const repeatHeight = start && head ? head.end - head.start : 0
      let end = Math.min(start + capacity - repeatHeight, canvas.height)
      for (let pass = 0; pass < blocks.length; pass++) {
        const crossing = blocks.filter(block => block.start < end - 3 && block.end > end + 3 && block.start > start)
        if (!crossing.length) break
        end = Math.min(...crossing.map(block => block.start))
      }
      if (end <= start) throw new Error('月报内容超出单页，请调整排版')
      const slice = document.createElement('canvas')
      slice.width = canvas.width
      slice.height = end - start + repeatHeight
      const context = slice.getContext('2d')
      if (repeatHeight) context.drawImage(canvas, 0, head.start, canvas.width, repeatHeight, 0, 0, canvas.width, repeatHeight)
      context.drawImage(canvas, 0, start, canvas.width, end - start, 0, repeatHeight, canvas.width, end - start)
      if (pageCount++) pdf.addPage()
      pdf.addImage(slice.toDataURL('image/png'), 'PNG', margin, margin, width, slice.height * scale, undefined, 'FAST')
      start = end
    }
  }
  pdf.save(filename)
  return pageCount
}
