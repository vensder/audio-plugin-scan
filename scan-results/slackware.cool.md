# Audio plugins on slackware.cool

- OS: Slackware 15.0 x86_64 (post 15.0 -current)
- User: vensder
- Scanned: 2026-11-09T11:30:25+13:00
- Plugin files/entries: 1112 (clap 6, dssi 6, jsfx 489, ladspa 124, lv2 414, vst2 66, vst3 7)

## System plugins (59)

- amp: ladspa
- amsynth: lv2, vst2
- amsynth_dssi: dssi
- balance: lv2
- calf: lv2 (49 plugins)
- controlfilter: lv2 (5 plugins)
- darc: lv2 (2 plugins)
- delay: ladspa
- dpl: lv2 (2 plugins)
- eg-amp: lv2
- eg-fifths: lv2
- eg-metro: lv2
- eg-midigate: lv2
- eg-params: lv2
- eg-sampler: lv2
- eg-scope: lv2 (2 plugins)
- fat1: lv2 (3 plugins)
- fil4: lv2 (2 plugins)
- filter: ladspa
- helm-synth: lv2, vst2
- karplong: dssi
- less_trivial_synth: dssi
- libzynaddsubfx_dssi: dssi
- lsp-plugins: clap, lv2 (198 plugins), vst2, vst3
- lsp-plugins-ladspa: ladspa
- matrixmixer: lv2
- meters: lv2 (36 plugins)
- mididebug: lv2
- midifilter: lv2 (34 plugins)
- midigen: lv2
- midimap: lv2
- mixtri: lv2
- nodelay: lv2 (3 plugins)
- noise: ladspa
- onsettrigger: lv2 (2 plugins)
- phaserotate: lv2 (2 plugins)
- sine: ladspa
- sisco: lv2 (4 plugins)
- spectra: lv2
- stepseq_s8n8: lv2
- stereoroute: lv2
- Surge XT: clap, lv2, vst3
- Surge XT Effects: clap, lv2, vst3
- testsignal: lv2
- trivial_sampler: dssi
- trivial_synth: dssi
- tuna: lv2 (2 plugins)
- VASTvaporizer2: clap, lv2, vst3
- xfade: lv2
- yoshimi: lv2 (2 plugins)
- zeroconvo: lv2 (6 plugins)
- ZynAddSubFX: lv2, vst2
- ZynAlienWah: lv2, vst2
- ZynChorus: lv2, vst2
- ZynDistortion: lv2, vst2
- ZynDynamicFilter: lv2, vst2
- ZynEcho: lv2, vst2
- ZynPhaser: lv2, vst2
- ZynReverb: lv2, vst2

## Home plugins in `/home/vensder` (4)

- avldrums: lv2 (9 plugins)
- TAL-NoiseMaker: clap, vst2, vst3
- TyrellN6: clap, vst3
- ZebraCM: vst3

## Carla (26)

- lv2: Audio File, Audio Gain (Mono), Audio Gain (Stereo), Big Meter, Carla-Patchbay, Carla-Patchbay (16chan), Carla-Patchbay (32chan), Carla-Patchbay (64chan), Carla-Patchbay (CV), Carla-Patchbay (sidechain), Carla-Rack, LFO, MIDI Channel A/B, MIDI Channel Filter, MIDI Channelize, MIDI File, MIDI Gain, MIDI Join, MIDI Pattern, MIDI Split, MIDI Transpose
- vst2: CarlaPatchbay, CarlaPatchbay16, CarlaPatchbay32, CarlaPatchbay64, CarlaPatchbayFX, CarlaRack, CarlaRackFX
- plus 8 Carla helper libraries

## REAPER

### Plugin paths

- reaper.ini: `/home/vensder/.config/REAPER/reaper.ini`
- clap paths: `/usr/local/lib/clap`; `/usr/lib/clap`; `~/.clap`; `/usr/lib64/clap`
- lv2 paths: `/usr/lib/lv2`; `/usr/local/lib/lv2`; `~/.lv2`; `/usr/lib64/lv2`
- vst paths: `~/.vst`; `~/.vst3`; `/usr/lib64/vst`; `/usr/lib64/vst3`

Installed, but outside REAPER's plugin paths (1):

- helm-synth: vst2

### FX, bundled (23)

- reacast: vst2
- reacomp: vst2
- reacontrolmidi: vst2
- readelay: vst2
- reaeq: vst2
- reafir: vst2
- reagate: vst2
- reainsert: vst2
- realimit: vst2
- reaninjam: vst2
- reapitch: vst2
- reasamplomatic: vst2
- reastream: vst2
- reasurround: vst2
- reasurround2: vst2
- reasyndr: vst2
- reasynth: vst2
- reatune: vst2
- reaverb: vst2
- reaverbate: vst2
- reavocode: vst2
- reavoice: vst2
- reaxcomp: vst2

### Other components, bundled (16)

- elastique3: vst2
- jsfx: vst2
- reaper_cd: vst2
- reaper_csurf: vst2
- reaper_ddp: vst2
- reaper_explorer: vst2
- reaper_flac: vst2
- reaper_midi: vst2
- reaper_mp3dec: vst2
- reaper_ogg: vst2
- reaper_opus: vst2
- reaper_video: vst2
- reaper_wave: vst2
- reaper_wavpack: vst2
- rubberband: vst2
- soundtouch: vst2

### JSFX (265)

- analysis (8): WigMCVUMeter, gain_reduction_scope, gfxanalyzer, gfxscope, gfxspectrograph, loudness_meter, spectropaint, zoomanalyzer
- chmaha-fx (31): AnalogEQ.jsfx, BitMeter.jsfx, ChronoDupe.jsfx, Compressor.jsfx, De-Esser.jsfx, Delay.jsfx, Dizzy.jsfx, DynamicTilt.jsfx, EQ.jsfx, FinalTouch.jsfx, Gate.jsfx, Inflator.jsfx, IntelligentSpectralCompressor.jsfx, JuKnowChorus.jsfx, K-Meter.jsfx, Limiter.jsfx, LoudnessMeter.jsfx, LuminaChannelStrip.jsfx, Maximizer.jsfx, MultibandCompressor.jsfx, MultibandCorrelationMeter.jsfx, NeedleMeter.jsfx, Phase-FrequencyWheel.jsfx, Reverb.jsfx, Saturation.jsfx, SpectrumAnalyzer.jsfx, Stereo-FrequencyScope.jsfx, StereoPhaseScope.jsfx, TestSignalGenerator.jsfx, TruePeak.jsfx, Tuner.jsfx
- chmaha-inst (8): ChamberOrgan.jsfx, DrNine.jsfx, JamSynth.jsfx, Jexed.jsfx, LordOfTheRinks.jsfx, MajorGeneralMIDI.jsfx, SynthyMcSynthface.jsfx, TolerableTines.jsfx
- delay (8): delay, delay_chfun, delay_chorus, delay_lowres, delay_sustain, delay_tone, delay_varlen, time_adjustment
- dynamics (1): general_dynamics
- filters (7): autopeakfilter, dc_remove, mdct-filter, mdct-volsweep, resonantlowpass, spectro_filter_paint, sweepinglowpass
- guitar (9): amp-model, amp-model-dual, chorus, distort-fuzz, distortion, flanger, phaser, tremolo, wah
- IX (16): MIDI_CCRider, MIDI_DuplicateFilter, MIDI_KeyMap, MIDI_KeySnap, MIDI_Router, MIDI_Tool, MIDI_Tool II, MIDI_Variant, MIDI_Velocifier II, MIDI_Wobulator, Mixer_8xM-1xS, Mixer_8xS-1xS, PhaseAdjustingRouter, StereoPhaseInvert, Switcher2, SwixMitch
- Liteon (23): 3bandpeakfilter, applefilter12db, applefilter72db, bassmanager, butterworth24db, cheby24db, deesser, lorenzattractor, moog24db, nonlinear, np1136peaklimiter, pinknoisegen, presenceeq, pseudostereo, rbjstereofilter12db, ringmodulator, shelvingfilter, simplelp6db, statevariable, tilteq, vumetergfx, vumetergfxsum, waveshapermulti
- loopsamplers (5): autoloop, loopsampler-granul, loopsampler-m2, loopsampler-m2-midi, super8
- loser (36): 3BandEQ, 3BandJoiner, 3BandSplitter, 4BandEQ, 4BandJoiner, 4BandSplitter, 50HzKicker, 5BandJoiner, 5BandSplitter, CenterCanceler, Compciter, DDC, DVC2JS, DVCJS, Exciter, MGA_JSLimiter, MGA_JSLimiterST, MIDI_EQ_Ducker, SP1LimiterJS, Saturation, StereoField, TimeDelayer, TransientController, TransientKiller, UpwardExpander, WhiteNoise, ZeroCrossingMaximizer, amplitudeModulator, gfxGoniometer, masterLimiter, phaseMeter, ppp, stereo, stereoEnhancer, timeDifferencePan, waveShapingDstr
- meters (2): bit_meter, dynamics_meter
- midi (23): drumtrigger, midi_CC_mapper, midi_arp, midi_choke, midi_choke_group, midi_chorderizer, midi_chordkey, midi_delay, midi_logger, midi_maptokey, midi_note2channel, midi_note_filter, midi_note_hold, midi_note_repeater, midi_note_sanitizer, midi_transpose, midi_velocitycontrol, midinoteondelay, mtc_logger, program_bank_onload, sequencer_baby, sequencer_baby_v2, sequencer_megababy
- misc (5): adpcm_simulator, reverseness, tonifier, tonifier2, video_sample_peeker
- old_unsupported (1): dither
- pitch (6): mdct-shift, octavedown, octaveup, pitch2, pitchdown, superpitch
- remaincalm_org (4): avocado_glitch, floaty_delay, paranoia_mangler, tonegate
- Saike Tools (2): Basics/Saike_Pitch_Shift.jsfx, SpectrumAnalyzer/SaikeMultiSpectralAnalyzer.jsfx
- schwa (7): audio_statistics, fft_splitter, gaussian_noise_generator, midi_examine, midi_humanizer, midi_modal_randomness, soft_clipper
- sstillwell (37): 1175, 3x3, 3x3_6dbSlope, 4x4, autoexpand, badbussmojo, badbussmojo_aa, chorus, chorus_stereo, delay_pong, delay_tempo, dirtsqueeze, eventhorizon, eventhorizon2, exciter, expander, expressbus, fairlychildish, fairlychildish2, flangebaby, hpflpf, hugebooty, louderizer, louderizer_lpf, majortom, mastertom, ozzifier, randomizer, rbj1073, rbj4eq, rbj7eq, realoud, realoud_lpf, stereowidth, thunderkick, volscale, width
- synthesis (3): sine_sweep, spectral_hold, tonegenerator
- Teej (3): rbj12eq-teej, rbj4eq-teej, rbj4notch-teej
- Till (5): Auto-Wideness v1.0, Transient-driven Auto-Pan v1.0 (Receiver), Transient-driven Auto-Pan v1.0 (Transmitter), Transient-driven Auto-Pan v1.1 (Receiver), Transient-driven Auto-Pan v1.1 (Transmitter)
- utility (13): KanakaMS5, KanakaMSEncoder1, chanmix2, channel_mapper, channelmixer, dither_psycho, phase_adjust, smpte_ltc_reader, vca_follow, vca_lead, volume, volume_pan, volume_pan_sample_accurate_auto
- waveshapers (2): graphdist, graphdist-dyn

## LMMS

### Bundled LADSPA (118)

alias_1407, allpass_1895, am_pitchshift_1433, amp_1181, analogue_osc_1416, bandpass_a_iir_1893, bandpass_iir_1892, bode_shifter_1431, bode_shifter_cv_1432, butterworth_1902, calf, caps, chebstortion_1430, cmt, comb_1190, comb_1887, comb_splitter_1411, const_1909, crossover_dist_1404, dc_remove_1207, decay_1886, decimator_1202, declip_1195, delay_1898, delayorama_1402, diode_1185, divider_1186, dj_eq_1901, dj_flanger_1438, dyson_compress_1403, fad_delay_1192, fast_lookahead_limiter_1913, flanger_1191, fm_osc_1415, foldover_1213, foverdrive_1196, freq_tracker_1418, gate_1410, giant_flange_1437, gong_1424, gong_beater_1439, gsm_1215, gverb_1216, hard_limiter_1413, harmonic_gen_1220, hermes_filter_1200, highpass_iir_1890, hilbert_1440, imp_1199, impulse_1885, inv_1429, karaoke_1409, latency_1914, lcr_delay_1436, lowpass_iir_1891, ls_filter_1908, matrix_ms_st_1421, matrix_spatialiser_1422, matrix_st_ms_1420, mbeq_1197, mod_delay_1419, multivoice_chorus_1201, notch_iir_1894, phasers_1217, pitch_scale_1193, pitch_scale_1194, plate_1423, pointer_cast_1910, rate_shifter_1417, retro_flange_1208, revdelay_1605, ringmod_1188, satan_maximiser_1408, sc1_1425, sc2_1426, sc3_1427, sc4_1882, sc4m_1916, se4_1883, shaper_1187, sifter_1210, sin_cos_1881, single_para_1203, sinus_wavewrapper_1198, smooth_decimate_1414, split_1406, step_muxer_1212, surround_encoder_1401, svf_1214, tap_autopan, tap_chorusflanger, tap_deesser, tap_doubler, tap_dynamics_m, tap_dynamics_st, tap_echo, tap_eq, tap_eqbw, tap_limiter, tap_pinknoise, tap_pitch, tap_reflector, tap_reverb, tap_rotspeak, tap_sigmoid, tap_tremolo, tap_tubewarmth, tap_vibrato, tape_delay_1211, transient_1206, triple_para_1204, valve_1209, valve_rect_1405, vocoder_1337, vynil_1905, wave_terrain_1412, xfade_1915, zm1_1428
