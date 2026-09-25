v {xschem version=3.4.5 file_version=1.2}
G {}
K {}
V {}
S {}
E {}
T {sky130-amp1-fom chipjev seed 0: inv} 0 -140 0 0 0.5 0.5 {}
T {ChipJev design on SKY130 (TT), VDD = 1.8 V} 0 -100 0 0 0.3 0.3 {}
C {sky130_fd_pr/nfet_01v8.sym} 0 0 0 0 {name=M1 L=2.01667 W=274.267 nf=6 mult=1 ad=39.7687 as=53.0249 pd=276.007 ps=368.009 nrd=0.00105737 nrs=0.00105737 sa=0 sb=0 sd=0 model=nfet_01v8 spiceprefix=X}
C {devices/lab_pin.sym} 20 -30 0 0 {name=l1 sig_type=std_logic lab=out}
C {devices/lab_pin.sym} -20 0 0 0 {name=l2 sig_type=std_logic lab=in}
C {devices/lab_pin.sym} 20 30 0 0 {name=l3 sig_type=std_logic lab=0}
C {devices/lab_pin.sym} 20 0 0 0 {name=l4 sig_type=std_logic lab=0}
C {sky130_fd_pr/pfet_01v8.sym} 240 0 0 0 {name=M2 L=2.01667 W=20.3683 nf=1 mult=1 ad=5.90682 as=5.90682 pd=41.3167 ps=41.3167 nrd=0.0142378 nrs=0.0142378 sa=0 sb=0 sd=0 model=pfet_01v8 spiceprefix=X}
C {devices/lab_pin.sym} 260 30 0 0 {name=l5 sig_type=std_logic lab=out}
C {devices/lab_pin.sym} 220 0 0 0 {name=l6 sig_type=std_logic lab=in}
C {devices/lab_pin.sym} 260 -30 0 0 {name=l7 sig_type=std_logic lab=vdd}
C {devices/lab_pin.sym} 260 0 0 0 {name=l8 sig_type=std_logic lab=vdd}
C {devices/vsource.sym} 480 0 0 0 {name=VDD value=1.8 m=1}
C {devices/lab_pin.sym} 480 -30 0 0 {name=l9 sig_type=std_logic lab=vdd}
C {devices/lab_pin.sym} 480 30 0 0 {name=l10 sig_type=std_logic lab=0}
