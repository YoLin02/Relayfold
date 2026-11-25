import re


async def publish(page, account, media_paths, title, description, *, before_submit):
    await page.goto("https://member.bilibili.com/platform/upload/video/frame", wait_until="domcontentloaded", timeout=45000)
    editor = page.frame_locator('iframe[src*="upload"]').first if await page.locator('iframe[src*="upload"]').count() else page
    file = editor.locator('input[type="file"][accept*="video"], input[type="file"][accept*="mp4"]').first
    if not await file.count():
        file = editor.locator('input[type="file"]').first
    await file.set_input_files(media_paths[0], timeout=30000)
    title_input = editor.get_by_placeholder(re.compile("请输入.*标题|稿件标题")).first
    await title_input.fill(title, timeout=180000)
    if description:
        summary = editor.locator('[contenteditable="true"]').first
        await summary.fill(description, timeout=12000)

    if account.bili_source == "转载":
        await editor.get_by_text("转载", exact=True).first.click(timeout=10000)
        await editor.get_by_placeholder(re.compile("转载.*来源|来源.*地址|输入来源")).first.fill(account.bili_origin, timeout=10000)
    else:
        await editor.get_by_text("自制", exact=True).first.click(timeout=10000)

    category = editor.get_by_placeholder(re.compile("选择.*分区|请选择.*分区")).first
    if not await category.count():
        category = editor.get_by_text(re.compile("^(选择分区|请选择分区)$")).first
    await category.click(timeout=12000)
    hierarchy = [part.strip() for part in account.bili_category.split("/") if part.strip()]
    for parent in hierarchy[:-1]:
        await editor.get_by_text(parent, exact=True).filter(visible=True).last.hover(timeout=12000)
    await editor.get_by_text(hierarchy[-1], exact=True).filter(visible=True).last.click(timeout=12000)
    if account.bili_tags:
        tags = editor.get_by_placeholder(re.compile("标签")).first
        for tag in account.bili_tags:
            await tags.fill(tag, timeout=10000)
            await tags.press("Enter")

    submit = editor.get_by_text(re.compile("^(立即投稿|投稿)$")).filter(visible=True).last
    await submit.click(trial=True, timeout=240000)
    await before_submit()
    await submit.click(timeout=12000)
    return True
