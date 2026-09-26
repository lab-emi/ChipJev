v {xschem version=3.4.5 file_version=1.2}
G {}
K {}
V {}
S {}
E {}
T {CHIPJEV / ota5_p+cs_p+miller} 40 -180 0 0 0.52 0.52 {layer=3}
T {01  DIFFERENTIAL INPUT + ACTIVE LOAD} 220 -100 0 0 0.32 0.32 {layer=6}
T {02  GAIN + COMPENSATION} 1230 -100 0 0 0.32 0.32 {layer=6}
T {SKY130 / 7 MOSFETs / W/L in um / live candidate} 40 1320 0 0 0.28 0.28 {layer=14}
N 40 100 1940 100 {}
N 40 100 40 470 {}
N 40 900 1940 900 {}
N 40 530 40 900 {}
N 580 170 580 100 {}
N 540 200 500 200 {}
N 580 260 580 230 {}
N 480 370 480 260 {}
N 480 260 720 260 {}
N 720 260 720 370 {}
N 640 400 680 400 {}
N 400 400 440 400 {}
N 720 900 720 790 {}
N 480 900 480 790 {}
N 720 730 720 430 {}
N 720 660 640 660 {}
N 640 660 640 760 {}
N 640 760 680 760 {}
N 480 730 480 430 {}
N 640 660 400 660 {}
N 400 660 400 760 {}
N 400 760 440 760 {}
N 480 500 1100 500 {}
N 1460 170 1460 100 {}
N 1100 500 1200 500 {}
N 1200 500 1200 200 {}
N 1200 200 1420 200 {}
N 1460 900 1460 810 {}
N 1460 750 1460 230 {}
N 1420 780 1340 780 {}
N 1460 500 1880 500 {}
N 1200 500 1200 0 {}
N 1200 0 1420 0 {}
N 1480 0 1880 0 {}
N 1880 0 1880 500 {}
N 500 200 500 1010 {}
N 500 1070 500 1260 {}
N 1340 780 1340 1010 {}
N 1340 1070 1340 1260 {}
N 40 900 40 1260 {}
N 40 1260 1940 1260 {}
C {devices/vsource.sym} 40 500 0 0 {name=VDD value=1.8 m=1 hide_texts=true}
T {VDD} 75 476 0 0 0.25 0.25 {layer=3}
T {1.8} 75 503 0 0 0.21 0.21 {layer=14}
C {devices/lab_wire.sym} 40 100 0 0 {name=net3 lab=vdd}
C {devices/lab_wire.sym} 40 900 0 0 {name=net4 lab=0}
C {sky130_fd_pr/pfet_01v8.sym} 560 200 0 0 {name=M1 L=2.4 W=24.24 nf=1 mult=1 ad=7.0296 as=7.0296 pd=49.06 ps=49.06 nrd=0.0119637 nrs=0.0119637 sa=0 sb=0 sd=0 model=pfet_01v8 spiceprefix=X hide_texts=true}
C {devices/lab_wire.sym} 580 200 0 0 {name=net6 lab=vdd hide_texts=true}
T {M1} 605 182 0 0 0.29 0.29 {layer=3}
T {24.2/2.4} 605 207 0 0 0.2 0.2 {layer=14}
C {devices/lab_wire.sym} 540 200 0 0 {name=net9 lab=s1t}
C {sky130_fd_pr/pfet_01v8.sym} 700 400 0 0 {name=M2 L=2.4 W=436.77 nf=9 mult=1 ad=70.3685 as=70.3685 pd=488.2 ps=488.2 nrd=0.000663965 nrs=0.000663965 sa=0 sb=0 sd=0 model=pfet_01v8 spiceprefix=X hide_texts=true}
C {devices/lab_wire.sym} 720 400 0 0 {name=net11 lab=vdd hide_texts=true}
T {M2} 745 382 0 0 0.29 0.29 {layer=3}
T {437/2.4} 745 407 0 0 0.2 0.2 {layer=14}
C {sky130_fd_pr/pfet_01v8.sym} 460 400 0 0 {name=M3 L=2.4 W=436.77 nf=9 mult=1 ad=70.3685 as=70.3685 pd=488.2 ps=488.2 nrd=0.000663965 nrs=0.000663965 sa=0 sb=0 sd=0 model=pfet_01v8 spiceprefix=X hide_texts=true}
C {devices/lab_wire.sym} 480 400 0 0 {name=net15 lab=vdd hide_texts=true}
T {M3} 505 382 0 0 0.29 0.29 {layer=3}
T {437/2.4} 505 407 0 0 0.2 0.2 {layer=14}
C {devices/lab_wire.sym} 580 260 0 0 {name=net18 lab=t1}
C {devices/lab_wire.sym} 640 400 0 0 {name=net19 lab=inp}
C {devices/lab_wire.sym} 400 400 0 0 {name=net20 lab=inn}
C {sky130_fd_pr/nfet_01v8.sym} 700 760 0 0 {name=M4 L=2.4 W=28.08 nf=1 mult=1 ad=8.1432 as=8.1432 pd=56.74 ps=56.74 nrd=0.0103276 nrs=0.0103276 sa=0 sb=0 sd=0 model=nfet_01v8 spiceprefix=X hide_texts=true}
C {devices/lab_wire.sym} 720 760 0 0 {name=net22 lab=0 hide_texts=true}
T {M4} 745 742 0 0 0.29 0.29 {layer=3}
T {28.1/2.4} 745 767 0 0 0.2 0.2 {layer=14}
C {sky130_fd_pr/nfet_01v8.sym} 460 760 0 0 {name=M5 L=2.4 W=28.08 nf=1 mult=1 ad=8.1432 as=8.1432 pd=56.74 ps=56.74 nrd=0.0103276 nrs=0.0103276 sa=0 sb=0 sd=0 model=nfet_01v8 spiceprefix=X hide_texts=true}
C {devices/lab_wire.sym} 480 760 0 0 {name=net26 lab=0 hide_texts=true}
T {M5} 505 742 0 0 0.29 0.29 {layer=3}
T {28.1/2.4} 505 767 0 0 0.2 0.2 {layer=14}
C {devices/lab_wire.sym} 720 730 0 0 {name=net29 lab=x1}
C {devices/lab_wire.sym} 480 730 0 0 {name=net30 lab=o1}
C {sky130_fd_pr/pfet_01v8.sym} 1440 200 0 0 {name=M6 L=0.15 W=36.45 nf=1 mult=1 ad=10.5705 as=10.5705 pd=73.48 ps=73.48 nrd=0.0079561 nrs=0.0079561 sa=0 sb=0 sd=0 model=pfet_01v8 spiceprefix=X hide_texts=true}
C {devices/lab_wire.sym} 1460 200 0 0 {name=net32 lab=vdd hide_texts=true}
T {M6} 1485 182 0 0 0.29 0.29 {layer=3}
T {36.5/0.15} 1485 207 0 0 0.2 0.2 {layer=14}
C {sky130_fd_pr/nfet_01v8.sym} 1440 780 0 0 {name=M7 L=0.15 W=3.6 nf=1 mult=1 ad=1.044 as=1.044 pd=7.78 ps=7.78 nrd=0.0805556 nrs=0.0805556 sa=0 sb=0 sd=0 model=nfet_01v8 spiceprefix=X hide_texts=true}
C {devices/lab_wire.sym} 1460 780 0 0 {name=net36 lab=0 hide_texts=true}
T {M7} 1485 762 0 0 0.29 0.29 {layer=3}
T {3.6/0.15} 1485 787 0 0 0.2 0.2 {layer=14}
C {devices/lab_wire.sym} 1460 750 0 0 {name=net39 lab=out}
C {devices/lab_wire.sym} 1420 780 0 0 {name=net40 lab=s2ld}
C {devices/capa.sym} 1450 0 1 0 {name=C8 value=2e-11 m=1 hide_texts=true}
T {C8} 1485 -24 0 0 0.25 0.25 {layer=3}
T {2e-11} 1485 3 0 0 0.21 0.21 {layer=14}
C {devices/vsource.sym} 500 1040 0 0 {name=V_S1T value=0.4175 m=1 hide_texts=true}
T {V_S1T} 535 1016 0 0 0.25 0.25 {layer=3}
T {0.4175} 535 1043 0 0 0.21 0.21 {layer=14}
C {devices/vsource.sym} 1340 1040 0 0 {name=V_S2LD value=1.5925 m=1 hide_texts=true}
T {V_S2LD} 1375 1016 0 0 0.25 0.25 {layer=3}
T {1.5925} 1375 1043 0 0 0.21 0.21 {layer=14}
