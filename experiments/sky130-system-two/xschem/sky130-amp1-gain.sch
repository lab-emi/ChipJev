v {xschem version=3.4.5 file_version=1.2}
G {}
K {}
V {}
S {}
E {}
T {sky130-amp1-gain chipjev seed 1: inv_cas} 0 -140 0 0 0.5 0.5 {}
T {ChipJev design on SKY130 (TT), VDD = 1.8 V} 0 -100 0 0 0.3 0.3 {}
C {sky130_fd_pr/nfet_01v8.sym} 0 0 0 0 {name=M1 L=1.2 W=10.488 nf=1 mult=1 ad=3.04152 as=3.04152 pd=21.556 ps=21.556 nrd=0.0276506 nrs=0.0276506 sa=0 sb=0 sd=0 model=nfet_01v8 spiceprefix=X}
C {devices/lab_pin.sym} 20 -30 0 0 {name=l1 sig_type=std_logic lab=s1a}
C {devices/lab_pin.sym} -20 0 0 0 {name=l2 sig_type=std_logic lab=in}
C {devices/lab_pin.sym} 20 30 0 0 {name=l3 sig_type=std_logic lab=0}
C {devices/lab_pin.sym} 20 0 0 0 {name=l4 sig_type=std_logic lab=0}
C {sky130_fd_pr/nfet_01v8.sym} 240 0 0 0 {name=M2 L=1.2 W=44.52 nf=1 mult=1 ad=12.9108 as=12.9108 pd=89.62 ps=89.62 nrd=0.00651393 nrs=0.00651393 sa=0 sb=0 sd=0 model=nfet_01v8 spiceprefix=X}
C {devices/lab_pin.sym} 260 -30 0 0 {name=l5 sig_type=std_logic lab=out}
C {devices/lab_pin.sym} 220 0 0 0 {name=l6 sig_type=std_logic lab=s1cn}
C {devices/lab_pin.sym} 260 30 0 0 {name=l7 sig_type=std_logic lab=s1a}
C {devices/lab_pin.sym} 260 0 0 0 {name=l8 sig_type=std_logic lab=0}
C {sky130_fd_pr/pfet_01v8.sym} 480 0 0 0 {name=M3 L=1.2 W=600 nf=12 mult=1 ad=87 as=101.5 pd=603.48 ps=704.06 nrd=0.000483333 nrs=0.000483333 sa=0 sb=0 sd=0 model=pfet_01v8 spiceprefix=X}
C {devices/lab_pin.sym} 500 30 0 0 {name=l9 sig_type=std_logic lab=out}
C {devices/lab_pin.sym} 460 0 0 0 {name=l10 sig_type=std_logic lab=s1cp}
C {devices/lab_pin.sym} 500 -30 0 0 {name=l11 sig_type=std_logic lab=s1c}
C {devices/lab_pin.sym} 500 0 0 0 {name=l12 sig_type=std_logic lab=vdd}
C {sky130_fd_pr/pfet_01v8.sym} 720 0 0 0 {name=M4 L=1.2 W=91.68 nf=2 mult=1 ad=13.2936 as=26.5872 pd=92.26 ps=184.52 nrd=0.00316318 nrs=0.00316318 sa=0 sb=0 sd=0 model=pfet_01v8 spiceprefix=X}
C {devices/lab_pin.sym} 740 30 0 0 {name=l13 sig_type=std_logic lab=s1c}
C {devices/lab_pin.sym} 700 0 0 0 {name=l14 sig_type=std_logic lab=in}
C {devices/lab_pin.sym} 740 -30 0 0 {name=l15 sig_type=std_logic lab=vdd}
C {devices/lab_pin.sym} 740 0 0 0 {name=l16 sig_type=std_logic lab=vdd}
C {devices/vsource.sym} 960 0 0 0 {name=VDD value=1.8 m=1}
C {devices/lab_pin.sym} 960 -30 0 0 {name=l17 sig_type=std_logic lab=vdd}
C {devices/lab_pin.sym} 960 30 0 0 {name=l18 sig_type=std_logic lab=0}
C {devices/vsource.sym} 1200 0 0 0 {name=V_S1CN value=0.98 m=1}
C {devices/lab_pin.sym} 1200 -30 0 0 {name=l19 sig_type=std_logic lab=s1cn}
C {devices/lab_pin.sym} 1200 30 0 0 {name=l20 sig_type=std_logic lab=0}
C {devices/vsource.sym} 0 200 0 0 {name=V_S1CP value=0.435 m=1}
C {devices/lab_pin.sym} 0 170 0 0 {name=l21 sig_type=std_logic lab=s1cp}
C {devices/lab_pin.sym} 0 230 0 0 {name=l22 sig_type=std_logic lab=0}
