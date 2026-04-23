# Live USB-camerabeeld via OpenCV.
# Eenmalig installeren: pip install opencv-python

import cv2


def main(camera_index: int = 1) -> None:
    cap = cv2.VideoCapture(camera_index, cv2.CAP_DSHOW)

    if not cap.isOpened():
        print(f"Kan camera met index {camera_index} niet openen. "
              "Is de USB-camera aangesloten?")
        return

    window_name = "USB Camera"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL | cv2.WINDOW_KEEPRATIO)
    print("Live beeld gestart. Druk op 'q' om te stoppen.")

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                print("Geen frame ontvangen van de camera.")
                break

            cv2.imshow(window_name, frame)

            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break

            if cv2.getWindowProperty(window_name, cv2.WND_PROP_VISIBLE) < 1:
                break
    finally:
        cap.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
