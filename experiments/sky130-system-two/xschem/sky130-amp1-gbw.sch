v {xschem version=3.4.5 file_version=1.2}
G {}
K {}
V {}
S {}
E {}
T {sky130-amp1-gbw chipjev seed 2: cs_n} 0 -140 0 0 0.5 0.5 {}
T {ChipJev design on SKY130 (TT), VDD = 1.8 V} 0 -100 0 0 0.3 0.3 {}
C {sky130_fd_pr/nfet_01v8.sym} 0 0 0 0 {name=M1 L=1.42667 W=713.333 nf=15 mult=1 ad=110.329 as=110.329 pd=765.529 ps=765.529 nrd=0.000406542 nrs=0.000406542 sa=0 sb=0 sd=0 model=nfet_01v8 spiceprefix=X}
C {devices/lab_pin.sym} 20 -30 0 0 {name=l1 sig_type=std_logic lab=out}
C {devices/lab_pin.sym} -20 0 0 0 {name=l2 sig_type=std_logic lab=in}
C {devices/lab_pin.sym} 20 30 0 0 {name=l3 sig_type=std_logic lab=0}
C {devices/lab_pin.sym} 20 0 0 0 {name=l4 sig_type=std_logic lab=0}
C {sky130_fd_pr/pfet_01v8.sym} 240 0 0 0 {name=M2 L=1.42667 W=713.333 nf=15 mult=1 ad=110.329 as=110.329 pd=765.529 ps=765.529 nrd=0.000406542 nrs=0.000406542 sa=0 sb=0 sd=0 model=pfet_01v8 spiceprefix=X}
C {devices/lab_pin.sym} 260 30 0 0 {name=l5 sig_type=std_logic lab=out}
C {devices/lab_pin.sym} 220 0 0 0 {name=l6 sig_type=std_logic lab=s1ld}
C {devices/lab_pin.sym} 260 -30 0 0 {name=l7 sig_type=std_logic lab=vdd}
C {devices/lab_pin.sym} 260 0 0 0 {name=l8 sig_type=std_logic lab=vdd}
C {devices/vsource.sym} 480 0 0 0 {name=VDD value=1.8 m=1}
C {devices/lab_pin.sym} 480 -30 0 0 {name=l9 sig_type=std_logic lab=vdd}
C {devices/lab_pin.sym} 480 30 0 0 {name=l10 sig_type=std_logic lab=0}
C {devices/vsource.sym} 720 0 0 0 {name=V_S1LD value=0.05 m=1}
C {devices/lab_pin.sym} 720 -30 0 0 {name=l11 sig_type=std_logic lab=s1ld}
C {devices/lab_pin.sym} 720 30 0 0 {name=l12 sig_type=std_logic lab=0}
