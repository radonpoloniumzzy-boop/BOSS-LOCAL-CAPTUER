import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiRequestError, downloadBatchMarkdown } from "./api";

describe("downloadBatchMarkdown", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("downloads markdown and revokes the blob url on success", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      blob: () => Promise.resolve(new Blob(["# batch markdown"])),
      headers: new Headers({ "Content-Disposition": "attachment; filename*=UTF-8''batch-55.md" }),
    } as Response);
    vi.stubGlobal("fetch", fetchMock);
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    const createObjectUrl = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:test");
    const revokeObjectUrl = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});

    await downloadBatchMarkdown(55);

    expect(fetchMock).toHaveBeenCalledWith("/api/capture-batches/55/export.md");
    expect(clickSpy).toHaveBeenCalledTimes(1);
    expect(createObjectUrl).toHaveBeenCalledTimes(1);
    expect(revokeObjectUrl).toHaveBeenCalledWith("blob:test");
  });

  it("wraps download failures safely and still revokes the blob url when click fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      blob: () => Promise.resolve(new Blob(["# batch markdown"])),
      headers: new Headers(),
    } as Response));
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {
      throw new Error("native click failure");
    });
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:test-fail");
    const revokeObjectUrl = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});

    await expect(downloadBatchMarkdown(77)).rejects.toMatchObject({
      code: "export_failed",
      message: "Markdown 导出失败，请稍后重试。",
    });
    expect(revokeObjectUrl).toHaveBeenCalledWith("blob:test-fail");
  });
});
