/* Link-time symbol stub for building the Kobo host without proprietary binaries.
 * Only exports the 14 standard Flutter Embedder C API symbols used by host.c
 * and runtime_test.c. At runtime, the dynamic linker resolves these against the
 * user's unmodified official libflutter_engine.so.
 */
void FlutterEngineCollectAOTData(void) {}
void FlutterEngineCreateAOTData(void) {}
void FlutterEngineGetCurrentTime(void) {}
void FlutterEngineNotifyDisplayUpdate(void) {}
void FlutterEngineRun(void) {}
void FlutterEngineRunTask(void) {}
void FlutterEngineRunsAOTCompiledDartCode(void) {}
void FlutterEngineScheduleFrame(void) {}
void FlutterEngineSendPlatformMessage(void) {}
void FlutterEngineSendPlatformMessageResponse(void) {}
void FlutterEngineSendPointerEvent(void) {}
void FlutterEngineSendWindowMetricsEvent(void) {}
void FlutterEngineShutdown(void) {}
void FlutterEngineUpdateLocales(void) {}
