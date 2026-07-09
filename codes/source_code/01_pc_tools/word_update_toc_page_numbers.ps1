$ErrorActionPreference = 'Stop'
$docPath = 'C:\Users\Cheng\Desktop\嵌入式大赛作品报告_视觉闭环自主泊车系统_竞赛提交版_最终提交整理版.docx'
$word = $null
$doc = $null
try {
    $word = New-Object -ComObject Word.Application
    $word.Visible = $false
    $word.DisplayAlerts = 0
    $doc = $word.Documents.Open($docPath, $false, $false, $false)

    # Replace placeholder with automatic TOC using Heading 1-3 styles, page numbers, and hyperlinks.
    $findRange = $doc.Content
    $find = $findRange.Find
    $find.Text = '__AUTO_TOC_PLACEHOLDER__'
    $found = $find.Execute()
    if (-not $found) { throw 'TOC placeholder not found' }
    $tocRange = $findRange.Duplicate
    $tocRange.Text = ''
    $tocRange.Collapse(0)  # wdCollapseEnd
    [void]$doc.TablesOfContents.Add($tocRange, $true, 1, 3, $false, '', $true, $true, $null, $true, $true, $true)

    # Add centered page numbers to each section footer.
    foreach ($section in $doc.Sections) {
        $section.PageSetup.DifferentFirstPageHeaderFooter = $false
        $footer = $section.Footers.Item(1) # wdHeaderFooterPrimary
        $footer.Range.Text = ''
        $footer.Range.ParagraphFormat.Alignment = 1 # wdAlignParagraphCenter
        [void]$footer.PageNumbers.Add(1, $true) # wdAlignPageNumberCenter, show on first page
    }

    # Update all fields including TOC and page numbers.
    foreach ($toc in $doc.TablesOfContents) { $toc.Update() }
    $doc.Fields.Update() | Out-Null
    $pages = $doc.ComputeStatistics(2)
    $words = $doc.ComputeStatistics(0)
    $doc.Save()
    Write-Output "WORD_TOC_PAGE_OK pages=$pages words=$words"
}
finally {
    if ($doc -ne $null) { $doc.Close($false) }
    if ($word -ne $null) { $word.Quit() }
}
