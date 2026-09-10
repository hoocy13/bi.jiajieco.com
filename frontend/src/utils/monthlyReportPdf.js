const A4_WIDTH = 595.28
const A4_HEIGHT = 841.89
const PAGE_MARGIN = 34
const HEADER_HEIGHT = 22
const FOOTER_HEIGHT = 22
const BLOCK_GAP = 12

function createSlice(source, startY, height) {
  const canvas = document.createElement('canvas')
  canvas.width = source.width
  canvas.height = height
  const context = canvas.getContext('2d')
  context.fillStyle = '#ffffff'
  context.fillRect(0, 0, canvas.width, canvas.height)
  context.drawImage(source, 0, startY, source.width, height, 0, 0, source.width, height)
  return canvas
}

function addPageFrame(pdf, pageNumber) {
  pdf.setDrawColor(226, 232, 240)
  pdf.setLineWidth(0.6)
  pdf.line(PAGE_MARGIN, A4_HEIGHT - FOOTER_HEIGHT, A4_WIDTH - PAGE_MARGIN, A4_HEIGHT - FOOTER_HEIGHT)
  pdf.setTextColor(100, 116, 139)
  pdf.setFontSize(8)
  pdf.text(String(pageNumber), A4_WIDTH - PAGE_MARGIN, A4_HEIGHT - 9, { align: 'right' })
}

export async function exportMonthlyReportPdf(root, filename) {
  if (!root) throw new Error('月报内容尚未完成渲染')

  const [{ jsPDF }, html2canvasModule] = await Promise.all([
    import('jspdf'),
    import('html2canvas'),
  ])
  const html2canvas = html2canvasModule.default
  await document.fonts?.ready
  await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))

  const blocks = [...root.querySelectorAll('.report-cover, .report-section')]
  if (!blocks.length) throw new Error('月报中没有可导出的内容')

  const pdf = new jsPDF({ orientation: 'portrait', unit: 'pt', format: 'a4', compress: true })
  const contentWidth = A4_WIDTH - PAGE_MARGIN * 2
  const contentTop = HEADER_HEIGHT + 10
  const contentBottom = A4_HEIGHT - FOOTER_HEIGHT - 10
  const usableHeight = contentBottom - contentTop
  let pageNumber = 1
  let cursorY = contentTop

  addPageFrame(pdf, pageNumber)

  for (const block of blocks) {
    const canvas = await html2canvas(block, {
      backgroundColor: '#ffffff',
      scale: Math.min(window.devicePixelRatio || 1, 2),
      logging: false,
      useCORS: true,
      windowWidth: root.scrollWidth,
    })
    const ratio = contentWidth / canvas.width
    const renderedHeight = canvas.height * ratio

    if (renderedHeight <= usableHeight) {
      if (cursorY > contentTop && cursorY + renderedHeight > contentBottom) {
        pdf.addPage()
        pageNumber += 1
        addPageFrame(pdf, pageNumber)
        cursorY = contentTop
      }
      pdf.addImage(canvas.toDataURL('image/jpeg', 0.94), 'JPEG', PAGE_MARGIN, cursorY, contentWidth, renderedHeight, undefined, 'FAST')
      cursorY += renderedHeight + BLOCK_GAP
      continue
    }

    let sourceY = 0
    while (sourceY < canvas.height) {
      if (cursorY > contentTop) {
        pdf.addPage()
        pageNumber += 1
        addPageFrame(pdf, pageNumber)
        cursorY = contentTop
      }
      const availablePoints = contentBottom - cursorY
      const sliceHeight = Math.min(canvas.height - sourceY, Math.max(1, Math.floor(availablePoints / ratio)))
      const slice = createSlice(canvas, sourceY, sliceHeight)
      const sliceRenderedHeight = sliceHeight * ratio
      pdf.addImage(slice.toDataURL('image/jpeg', 0.94), 'JPEG', PAGE_MARGIN, cursorY, contentWidth, sliceRenderedHeight, undefined, 'FAST')
      sourceY += sliceHeight
      cursorY += sliceRenderedHeight + BLOCK_GAP
      if (sourceY < canvas.height) cursorY = contentBottom
    }
  }

  pdf.save(filename)
  return pageNumber
}
