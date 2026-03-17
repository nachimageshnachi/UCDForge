@echo off
setlocal

:: ─────────────────────────────────────────────────────────────────────────────
:: myCBR REST API Server Launcher
:: ─────────────────────────────────────────────────────────────────────────────
:: Starts the myCBR REST API at http://localhost:8080
:: Swagger UI: http://localhost:8080/swagger-ui/index.html
:: Press Ctrl+C to stop the server.
:: ─────────────────────────────────────────────────────────────────────────────

echo.
echo  ┌─────────────────────────────────────────────────────┐
echo  │           myCBR REST Server Launcher                 │
echo  │   Swagger UI: http://localhost:8080/swagger-ui       │
echo  │   Press Ctrl+C to stop                               │
echo  └─────────────────────────────────────────────────────┘
echo.

:: Path to the myCBR project .prj file
set PRJ_FILE=C:\Users\mages\OneDrive\Desktop\FYP\METHODOLOGICAL_ASSISTANT\Software\CBR\MyCBR\output\UCD_CBR_Cycle_Project\UCD_CBR_Cycle_Project.prj

:: Path to the REST server JAR
set JAR_FILE=C:\Users\mages\mycbr-rest\target\mycbr-rest-2.1.jar

:: Java executable
set JAVA_EXE="C:\Program Files\Java\jdk-25\bin\java.exe"

:: Validate files exist
if not exist "%PRJ_FILE%" (
    echo ERROR: myCBR project file not found: %PRJ_FILE%
    pause
    exit /b 1
)
if not exist "%JAR_FILE%" (
    echo ERROR: myCBR REST JAR not found: %JAR_FILE%
    pause
    exit /b 1
)

echo  Loading project: %PRJ_FILE%
echo  Starting server...
echo.

%JAVA_EXE% -DMYCBR.PROJECT.FILE="%PRJ_FILE%" -jar "%JAR_FILE%"

endlocal
