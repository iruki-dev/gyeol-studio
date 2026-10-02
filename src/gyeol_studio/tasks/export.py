"""Export job (copies audio, writes manifest files)."""

from __future__ import annotations

from .. import exporting
from ..jobs import JobContext, UserError
from . import register


def export_data(ctx: JobContext) -> dict:
    kind, scope = ctx.params.get("kind"), ctx.params.get("scope", "all")
    if scope not in exporting.SCOPES:
        raise UserError("내보내기 범위를 다시 골라 주세요.")
    prog = lambda f, m: ctx.progress(0.05 + 0.9 * f, m)  # noqa: E731
    if kind == exporting.EVAL:
        r = exporting.export_eval(ctx.conn, ctx.layout, scope, prog)
    elif kind == exporting.TRAIN:
        r = exporting.export_train(ctx.conn, ctx.layout, scope, prog)
    else:
        raise UserError("내보내기 종류를 다시 골라 주세요.")
    if r["takes"] == 0:
        import shutil

        shutil.rmtree(r["dir"], ignore_errors=True)
        raise UserError("내보낼 녹음이 없어요. 학습 동의를 받은 녹음이 있어야 하고, 학습용은 발성·음질 라벨도 필요해요.")
    return r


register("export_data", export_data)
