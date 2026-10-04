@echo off
chcp 65001 >nul
rem 一键运行：找 Python → 建虚拟环境 → 按 requirements.txt 装依赖 → 自检 → 启动 app.py
rem 双击即可。依赖已装好时会跳过安装，第二次起几秒就能打开。
setlocal
cd /d "%~dp0"
title Serial Actuator Lab

set "VENV=%~dp0.venv"
set "VPY=%VENV%\Scripts\python.exe"
set "STAMP=%VENV%\requirements.installed"

echo.
echo [1/5] 检查 Python ...
if exist "%VPY%" (
    echo       已有虚拟环境 .venv，直接使用。
    goto deps
)
set "PYLAUNCH="
py -3 -c "import sys" >nul 2>&1 && set "PYLAUNCH=py -3"
if not defined PYLAUNCH (
    python -c "import sys" >nul 2>&1 && set "PYLAUNCH=python"
)
if not defined PYLAUNCH (
    echo       没找到 Python。
    echo       请到 https://www.python.org/downloads/ 安装 Python 3.12，
    echo       安装时勾选 "Add python.exe to PATH"，然后再双击本文件。
    goto failed
)
%PYLAUNCH% -c "import sys; sys.exit(0 if (3, 8) <= sys.version_info[:2] <= (3, 13) else 1)"
if errorlevel 1 (
    echo       Python 版本不合适，需要 3.8 到 3.13，推荐 3.12。当前版本：
    %PYLAUNCH% --version
    goto failed
)
%PYLAUNCH% --version

echo.
echo [2/5] 创建虚拟环境 .venv（只在第一次做）...
%PYLAUNCH% -m venv "%VENV%"
if errorlevel 1 (
    echo       创建虚拟环境失败。
    goto failed
)

:deps
echo.
echo [3/5] 检查依赖（requirements.txt）...
if not exist "requirements.txt" (
    echo       找不到 requirements.txt，请确认整个文件夹都解压出来了。
    goto failed
)
set "NEED_INSTALL=1"
if exist "%STAMP%" (
    fc /b "requirements.txt" "%STAMP%" >nul 2>&1 && set "NEED_INSTALL="
)
if not defined NEED_INSTALL (
    "%VPY%" -c "import panda3d.core" >nul 2>&1 || set "NEED_INSTALL=1"
)
if defined NEED_INSTALL (
    echo       正在用 pip 安装依赖，第一次可能要几分钟 ...
    "%VPY%" -m pip install --disable-pip-version-check -r requirements.txt
    if errorlevel 1 (
        echo       依赖安装失败。请检查网络后再双击一次。
        goto failed
    )
    copy /y "requirements.txt" "%STAMP%" >nul
) else (
    echo       依赖已经装好，跳过。
)

echo.
echo [4/5] 自检 ...
"%VPY%" -c "import panda3d.core, protocol" >nul 2>&1
if errorlevel 1 (
    echo       依赖导入失败，正在重新安装 ...
    "%VPY%" -m pip install --disable-pip-version-check --force-reinstall -r requirements.txt
    "%VPY%" -c "import panda3d.core, protocol"
    if errorlevel 1 goto failed
    copy /y "requirements.txt" "%STAMP%" >nul
)
"%VPY%" -m unittest -q test_protocol >nul 2>&1
if errorlevel 1 (
    echo       协议自检没有通过，详细信息如下：
    "%VPY%" -m unittest test_protocol
    goto failed
)
echo       协议自检通过。
if not defined SERVO_LAB_FONT if not exist "%WINDIR%\Fonts\msyh.ttc" (
    echo       提示：没找到微软雅黑字体 msyh.ttc。界面需要中文字体，
    echo       可以把环境变量 SERVO_LAB_FONT 设成任意中文字体文件的路径。
)

echo.
echo [5/5] 启动实验室 ...
"%VPY%" "%~dp0app.py" %*
if errorlevel 1 (
    echo       程序异常退出，上面是错误信息。
    goto failed
)
exit /b 0

:failed
echo.
echo 没能启动。请把上面的信息截图发给我。
pause
exit /b 1
