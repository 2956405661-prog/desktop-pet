# -*- coding: utf-8 -*-
"""一个 exe，两种身份：

    桌面宠物.exe               -> 把宠物叫起来（窗口）
    桌面宠物.exe --hook        -> 当 Claude Code 的钩子用（读 stdin 的那份 JSON）

这样安装包里只有一个可执行文件，钩子也不用再依赖"机器上有没有 Python"。
"""
from __future__ import annotations

import sys


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] in ("--hook", "-hook", "--pet-hook"):
        import claude_pet_hook
        return claude_pet_hook.main()
    if len(sys.argv) > 1 and sys.argv[1] in ("--setup", "--install", "-setup"):
        import 设置向导
        return 设置向导.main(["--setup"])
    if len(sys.argv) > 1 and sys.argv[1] in ("--uninstall", "--remove", "--unsetup"):
        import 设置向导
        return 设置向导.main(["--uninstall"])
    import pet
    return pet.main()


if __name__ == "__main__":
    raise SystemExit(main())
