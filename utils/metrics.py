# Model validation metrics

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import torch
import torchmetrics

from . import general


def fitness(x):
    # Model fitness as a weighted combination of metrics
    w = [0.0, 0.0, 0.1, 0.9]  # weights for [P, R, mAP@0.5, mAP@0.5:0.95]
    return (x[:, :4] * w).sum(1)


def fitness_roc(x):
    # "val_(f)roc/lesion_auc",
    # "val_(f)roc/image_auc",
    # "val_(f)roc/image_auc_nonloc",
    # "val_(f)roc/lesion_pauc_froc",
    # "val_(f)roc/image_pauc_froc",
    # "val_(f)roc/image_pauc_nonloc_froc",
    return x[0][2]


def ap_per_class(tp, conf, pred_cls, target_cls, plot=False, save_dir=".", names=()):
    """Compute the average precision, given the recall and precision curves.
    Source: https://github.com/rafaelpadilla/Object-Detection-Metrics.
    # Arguments
        tp:  True positives (nparray, nx1 or nx10).
        conf:  Objectness value from 0-1 (nparray).
        pred_cls:  Predicted object classes (nparray).
        target_cls:  True object classes (nparray).
        plot:  Plot precision-recall curve at mAP@0.5
        save_dir:  Plot save directory
    # Returns
        The average precision as computed in py-faster-rcnn.
    """

    # Sort by objectness
    i = np.argsort(-conf)
    tp, conf, pred_cls = tp[i], conf[i], pred_cls[i]

    # Find unique classes
    unique_classes = np.unique(target_cls)
    nc = unique_classes.shape[0]  # number of classes, number of detections

    # Create Precision-Recall curve and compute AP for each class
    px, py = np.linspace(0, 1, 1000), []  # for plotting
    ap, p, r = np.zeros((nc, tp.shape[1])), np.zeros((nc, 1000)), np.zeros((nc, 1000))
    for ci, c in enumerate(unique_classes):
        i = pred_cls == c
        n_l = (target_cls == c).sum()  # number of labels
        n_p = i.sum()  # number of predictions

        if n_p == 0 or n_l == 0:
            continue
        else:
            # Accumulate FPs and TPs
            fpc = (1 - tp[i]).cumsum(0)
            tpc = tp[i].cumsum(0)

            # Recall
            recall = tpc / (n_l + 1e-16)  # recall curve
            r[ci] = np.interp(-px, -conf[i], recall[:, 0], left=0)  # negative x, xp because xp decreases

            # Precision
            precision = tpc / (tpc + fpc)  # precision curve
            p[ci] = np.interp(-px, -conf[i], precision[:, 0], left=1)  # p at pr_score

            # AP from recall-precision curve
            for j in range(tp.shape[1]):
                ap[ci, j], mpre, mrec = compute_ap(recall[:, j], precision[:, j])
                if plot and j == 0:
                    py.append(np.interp(px, mrec, mpre))  # precision at mAP@0.5

    # Compute F1 (harmonic mean of precision and recall)
    f1 = 2 * p * r / (p + r + 1e-16)
    if plot:
        plot_pr_curve(px, py, ap, Path(save_dir) / "PR_curve.png", names)
        plot_mc_curve(px, f1, Path(save_dir) / "F1_curve.png", names, ylabel="F1")
        plot_mc_curve(px, p, Path(save_dir) / "P_curve.png", names, ylabel="Precision")
        plot_mc_curve(px, r, Path(save_dir) / "R_curve.png", names, ylabel="Recall")

    i = f1.mean(0).argmax()  # max F1 index
    return p[:, i], r[:, i], ap, f1[:, i], unique_classes.astype("int32")


def compute_ap(recall, precision):
    """Compute the average precision, given the recall and precision curves
    # Arguments
        recall:    The recall curve (list)
        precision: The precision curve (list)
    # Returns
        Average precision, precision curve, recall curve
    """

    # Append sentinel values to beginning and end
    mrec = np.concatenate(([0.0], recall, [recall[-1] + 0.01]))
    mpre = np.concatenate(([1.0], precision, [0.0]))

    # Compute the precision envelope
    mpre = np.flip(np.maximum.accumulate(np.flip(mpre)))

    # Integrate area under curve
    method = "interp"  # methods: 'continuous', 'interp'
    if method == "interp":
        x = np.linspace(0, 1, 101)  # 101-point interp (COCO)
        ap = np.trapz(np.interp(x, mrec, mpre), x)  # integrate
    else:  # 'continuous'
        i = np.where(mrec[1:] != mrec[:-1])[0]  # points where x axis (recall) changes
        ap = np.sum((mrec[i + 1] - mrec[i]) * mpre[i + 1])  # area under curve

    return ap, mpre, mrec


class ConfusionMatrix:
    # Updated version of https://github.com/kaanakan/object_detection_confusion_matrix
    def __init__(self, nc, conf=0.25, iou_thres=0.45):
        self.matrix = np.zeros((nc + 1, nc + 1))
        self.nc = nc  # number of classes
        self.conf = conf
        self.iou_thres = iou_thres

    def process_batch(self, detections, labels):
        """
        Return intersection-over-union (Jaccard index) of boxes.
        Both sets of boxes are expected to be in (x1, y1, x2, y2) format.
        Arguments:
            detections (Array[N, 6]), x1, y1, x2, y2, conf, class
            labels (Array[M, 5]), class, x1, y1, x2, y2
        Returns:
            None, updates confusion matrix accordingly
        """
        detections = detections[detections[:, 4] > self.conf]
        gt_classes = labels[:, 0].int()
        detection_classes = detections[:, 5].int()
        iou = general.box_iou(labels[:, 1:], detections[:, :4])

        x = torch.where(iou > self.iou_thres)
        if x[0].shape[0]:
            matches = torch.cat((torch.stack(x, 1), iou[x[0], x[1]][:, None]), 1).cpu().numpy()
            if x[0].shape[0] > 1:
                matches = matches[matches[:, 2].argsort()[::-1]]
                matches = matches[np.unique(matches[:, 1], return_index=True)[1]]
                matches = matches[matches[:, 2].argsort()[::-1]]
                matches = matches[np.unique(matches[:, 0], return_index=True)[1]]
        else:
            matches = np.zeros((0, 3))

        n = matches.shape[0] > 0
        m0, m1, _ = matches.transpose().astype(np.int16)
        for i, gc in enumerate(gt_classes):
            j = m0 == i
            if n and sum(j) == 1:
                self.matrix[gc, detection_classes[m1[j]]] += 1  # correct
            else:
                self.matrix[self.nc, gc] += 1  # background FP

        if n:
            for i, dc in enumerate(detection_classes):
                if not any(m1 == i):
                    self.matrix[dc, self.nc] += 1  # background FN

    def matrix(self):
        return self.matrix

    def plot(self, save_dir="", names=()):
        try:
            import seaborn as sn

            array = self.matrix / (self.matrix.sum(0).reshape(1, self.nc + 1) + 1e-6)  # normalize
            array[array < 0.005] = np.nan  # don't annotate (would appear as 0.00)

            fig = plt.figure(figsize=(12, 9), tight_layout=True)
            sn.set(font_scale=1.0 if self.nc < 50 else 0.8)  # for label size
            labels = (0 < len(names) < 99) and len(names) == self.nc  # apply names to ticklabels
            sn.heatmap(
                array,
                annot=self.nc < 30,
                annot_kws={"size": 8},
                cmap="Blues",
                fmt=".2f",
                square=True,
                xticklabels=names + ["background FP"] if labels else "auto",
                yticklabels=names + ["background FN"] if labels else "auto",
            ).set_facecolor((1, 1, 1))
            fig.axes[0].set_xlabel("True")
            fig.axes[0].set_ylabel("Predicted")
            fig.savefig(Path(save_dir) / "confusion_matrix.png", dpi=250)
        except Exception as e:
            pass

    def print(self):
        for i in range(self.nc + 1):
            print(" ".join(map(str, self.matrix[i])))


class OD_AUCROC:
    # Updated version of https://github.com/kaanakan/object_detection_confusion_matrix
    def __init__(self, nc, iou_thres=0.5, fm_img_ths=1.0):
        # self.matrix = np.zeros((nc + 1, nc + 1))
        # if nc == 1:
        self.roc_lesion = torchmetrics.ROC(num_classes=None)
        self.roc_image = torchmetrics.ROC(num_classes=None)
        self.roc_image_noloc = torchmetrics.ROC(num_classes=None)
        self.class_modifier = 1
        # else:
        #     self.roc_lesion = torchmetrics.ROC(num_classes=nc)
        #     self.roc_image = torchmetrics.ROC(num_classes=nc)
        #     self.roc_image_noloc = torchmetrics.ROC(num_classes=nc)
        #     self.class_modifier = 0
        self.markers_in_normal_image = []
        self.nc = nc  # number of classes
        self.iou_thres = iou_thres
        self.fm_img_ths = fm_img_ths
        if nc == 4:
            self.malignant_cls_th = 2
        elif nc == 2:
            self.malignant_cls_th = 1
        elif nc == 1:
            self.malignant_cls_th = 0
        else:
            raise ValueError("nc should be 1, 2 or 4")

    def process_batch(self, detections, labels):
        """
        Return intersection-over-union (Jaccard index) of boxes.
        Both sets of boxes are expected to be in (x1, y1, x2, y2) format.
        Arguments:
            detections (Array[N, 6]), x1, y1, x2, y2, conf, class
            labels (Array[M, 5]), class, x1, y1, x2, y2
        Returns:
            None, updates confusion matrix accordingly
        """
        # detections = detections[detections[:, 4] > self.conf]

        mal_detections = detections[detections[:, 5] >= self.malignant_cls_th]
        mal_labels = labels[labels[:, 0] >= self.malignant_cls_th]
        mal_detections[:, 5] = 0
        mal_labels[:, 0] = 0

        detection_probs = mal_detections[:, 4].cpu()
        nl = len(mal_labels)
        if len(mal_detections) == 0:
            if nl == 0:
                self.markers_in_normal_image.append(detection_probs)
                self.roc_lesion.update(torch.Tensor([0.0]), torch.Tensor([0.0]))
                self.roc_image.update(torch.Tensor([0.0]), torch.Tensor([0.0]))
                self.roc_image_noloc.update(torch.Tensor([0.0]), torch.Tensor([0.0]))
            else:
                self.roc_lesion.update(torch.Tensor([0.0] * nl), torch.Tensor([1.0] * nl))
                self.roc_image.update(torch.Tensor([0.0]), torch.Tensor([1.0]))
                self.roc_image_noloc.update(torch.Tensor([0.0]), torch.Tensor([1.0]))
            return
        else:
            if nl == 0:
                self.markers_in_normal_image.append(detection_probs)
                self.roc_lesion.update(torch.max(detection_probs, 0, keepdim=True)[0], torch.Tensor([0.0]))
                self.roc_image.update(torch.max(detection_probs, 0, keepdim=True)[0], torch.Tensor([0.0]))
                self.roc_image_noloc.update(torch.max(detection_probs, 0, keepdim=True)[0], torch.Tensor([0.0]))
                return
            else:
                self.roc_image_noloc.update(torch.max(detection_probs, 0, keepdim=True)[0], torch.Tensor([1.0]))

        gt_classes = mal_labels[:, 0].int() + self.class_modifier
        detection_classes = mal_detections[:, 5].int() + self.class_modifier
        iou = general.box_iou(mal_labels[:, 1:], mal_detections[:, :4])

        x = torch.where(iou > self.iou_thres)
        if x[0].shape[0]:
            matches = torch.cat((torch.stack(x, 1), iou[x[0], x[1]][:, None]), 1).cpu().numpy()
            # if x[0].shape[0] > 1:
            #     matches = matches[matches[:, 2].argsort()[::-1]]
            #     matches = matches[np.unique(matches[:, 1], return_index=True)[1]]
            #     matches = matches[matches[:, 2].argsort()[::-1]]
            #     matches = matches[np.unique(matches[:, 0], return_index=True)[1]]
        else:
            matches = np.zeros((0, 3))

        n = matches.shape[0] > 0
        # m0: label indices, m1: detection indices
        m0, m1, _ = matches.transpose().astype(np.int16)

        image_best_score = torch.Tensor([0.0])
        for i, gc in enumerate(gt_classes):
            j = m0 == i
            if n and sum(j) > 0 and any(detection_classes[m1[j]] == gc):
                best_score = torch.Tensor([0.0])
                for idc, dc in enumerate(detection_classes[m1[j]]):
                    if dc == gc:
                        best_score = torch.max(best_score, detection_probs[m1[j]][idc])
                        image_best_score = torch.max(image_best_score, best_score)
                self.roc_lesion.update(best_score, torch.Tensor([gc]))
            else:
                self.roc_lesion.update(torch.Tensor([0.0]), torch.Tensor([gc]))
        # This cannot be multi-class based on image level definition
        if nl > 0:
            self.roc_image.update(image_best_score, torch.Tensor([1.0]))

    def score(self):
        # Lesion level
        lesion_fpr, lesion_tpr, lesion_thresholds = self.roc_lesion.compute()

        froc_lesion_tpr, froc_lesion_fm_img = self.froc_curve(lesion_tpr, lesion_thresholds)
        auc_roc_lesion = torchmetrics.functional.auc(lesion_fpr, lesion_tpr)
        partial_fm_img_idx = froc_lesion_fm_img <= self.fm_img_ths
        pauc_froc_lesion = torchmetrics.functional.auc(
            froc_lesion_tpr[partial_fm_img_idx], froc_lesion_fm_img[partial_fm_img_idx]
        )

        # Image level
        ## roc
        image_fpr, image_tpr, image_thresholds = self.roc_image.compute()

        auc_roc_image = torchmetrics.functional.auc(image_fpr, image_tpr)
        froc_image_tpr, froc_image_fm_img = self.froc_curve(image_tpr, image_thresholds)
        partial_fm_img_idx = froc_image_fm_img <= self.fm_img_ths
        pauc_froc_image = torchmetrics.functional.auc(
            froc_image_tpr[partial_fm_img_idx], froc_image_fm_img[partial_fm_img_idx]
        )

        # Image level non-local
        image_nonlocal_frp, image_nonlocal_tpr, image_nonlocal_thresholds = self.roc_image_noloc.compute()

        auc_roc_image_nonloc = torchmetrics.functional.auc(image_nonlocal_frp, image_nonlocal_tpr)
        froc_image_nonloc_tpr, froc_image_nonloc_fm_img = self.froc_curve(image_nonlocal_tpr, image_nonlocal_thresholds)
        partial_fm_img_idx = froc_image_nonloc_fm_img <= self.fm_img_ths
        pauc_froc_image_nonloc = torchmetrics.functional.auc(
            froc_image_nonloc_tpr[partial_fm_img_idx], froc_image_nonloc_fm_img[partial_fm_img_idx]
        )
        return (
            auc_roc_lesion.item(),
            auc_roc_image.item(),
            auc_roc_image_nonloc.item(),
            pauc_froc_lesion.item(),
            pauc_froc_image.item(),
            pauc_froc_image_nonloc.item(),
        )

    def froc_curve(self, tpr, thresholds):
        avg_fm_image_per_ths = []
        n_normal_images = len(self.markers_in_normal_image)
        for threshold in thresholds:
            markers = torch.cat(self.markers_in_normal_image)
            avg_fm_image = torch.sum(markers > threshold) / n_normal_images
            avg_fm_image_per_ths.append(avg_fm_image)
        return tpr, torch.stack(avg_fm_image_per_ths)

    def plot(self):

        # plot roc curve using matplotlib
        image_fpr, image_tpr, image_thresholds = self.roc_image.compute()
        lesion_fpr, lesion_tpr, lesion_thresholds = self.roc_lesion.compute()
        image_roc_auc = torchmetrics.functional.auc(image_fpr, image_tpr).item()
        lesion_roc_auc = torchmetrics.functional.auc(lesion_fpr, lesion_tpr).item()
        plt.title("ROC Curve")
        plt.plot(
            image_fpr,
            image_tpr,
            marker=".",
            color="green",
            label="Image ROC_AUC = %0.2f" % image_roc_auc,
        )

        plt.plot(
            lesion_fpr,
            lesion_tpr,
            marker="-",
            color="red",
            label="Lesion ROC_AUC = %0.2f" % lesion_roc_auc,
        )
        # axis labels
        plt.xlabel("False Positive Rate")
        plt.ylabel("True Positive Rate")
        # show the legend
        plt.legend()
        # show the plot
        plt.show()

    def print(self):
        print(
            "lesion roc auc: ",
            self.roc_lesion.compute(),
            "image roc auc: ",
            self.roc_image.compute(),
        )


def plot_pr_curve(px, py, ap, save_dir="pr_curve.png", names=()):
    # Precision-recall curve
    fig, ax = plt.subplots(1, 1, figsize=(9, 6), tight_layout=True)
    py = np.stack(py, axis=1)

    if 0 < len(names) < 21:  # display per-class legend if < 21 classes
        for i, y in enumerate(py.T):
            ax.plot(px, y, linewidth=1, label=f"{names[i]} {ap[i, 0]:.3f}")  # plot(recall, precision)
    else:
        ax.plot(px, py, linewidth=1, color="grey")  # plot(recall, precision)

    ax.plot(
        px,
        py.mean(1),
        linewidth=3,
        color="blue",
        label="all classes %.3f mAP@0.5" % ap[:, 0].mean(),
    )
    ax.set_xlabel("Recall")
    ax.set_ylabel("Precision")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    plt.legend(bbox_to_anchor=(1.04, 1), loc="upper left")
    fig.savefig(Path(save_dir), dpi=250)


def plot_mc_curve(px, py, save_dir="mc_curve.png", names=(), xlabel="Confidence", ylabel="Metric"):
    # Metric-confidence curve
    fig, ax = plt.subplots(1, 1, figsize=(9, 6), tight_layout=True)

    if 0 < len(names) < 21:  # display per-class legend if < 21 classes
        for i, y in enumerate(py):
            ax.plot(px, y, linewidth=1, label=f"{names[i]}")  # plot(confidence, metric)
    else:
        ax.plot(px, py.T, linewidth=1, color="grey")  # plot(confidence, metric)

    y = py.mean(0)
    ax.plot(
        px,
        y,
        linewidth=3,
        color="blue",
        label=f"all classes {y.max():.2f} at {px[y.argmax()]:.3f}",
    )
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    plt.legend(bbox_to_anchor=(1.04, 1), loc="upper left")
    fig.savefig(Path(save_dir), dpi=250)
